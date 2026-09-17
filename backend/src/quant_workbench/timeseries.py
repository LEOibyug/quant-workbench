"""Offline initialization and causal online price/volume learning, without network calls."""

import copy
import math
from collections import deque
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from sklearn import __version__ as sklearn_version
from sklearn.linear_model import SGDClassifier, SGDRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from quant_workbench.market_data import normalize_bars

MODEL_VERSION = "online-sgd-v2-dual"
MAX_TRAINING_SAMPLES = 100_000
FEATURE_NAMES = [
    "return_1",
    "return_quarter",
    "return_half",
    "return_window",
    "return_volatility",
    "volume_ratio",
    "range_fraction",
    "sma_distance",
]


class TimeSeriesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    enabled: bool = False
    k: int = Field(default=30, ge=5, le=120)
    horizon: Literal[1] = 1
    probability_threshold: float = Field(default=0.55, ge=0.5, le=0.95)
    min_training_samples: int = Field(default=200, ge=50, le=10_000)
    max_iter: int = Field(default=5, ge=1, le=20)
    min_return_bps: float = Field(default=0, ge=0, le=1000)
    online_learning_rate: float = Field(default=0.001, ge=0.000001, le=0.01)
    adapt: bool = True
    cost_aware: bool = False
    cost_multiplier: float = Field(default=1.5, ge=1, le=10)
    min_edge_bps: float = Field(default=1, ge=0, le=100)


def _segments(frame):
    day = frame.timestamp.dt.tz_convert("America/New_York").dt.date
    return (
        frame.symbol.ne(frame.symbol.shift())
        | day.ne(day.shift())
        | frame.timestamp.diff().ne(pd.Timedelta(minutes=1))
    ).cumsum()


def _feature_rows(frame, k=30):
    groups = frame.groupby(_segments(frame), sort=False)
    features = pd.DataFrame(index=frame.index)
    for name, lag in zip(FEATURE_NAMES[:4], (1, max(1, k // 4), k // 2, k - 1), strict=True):
        features[name] = frame.close / groups.close.shift(lag) - 1
    returns = frame.close / groups.close.shift(1) - 1
    features["return_volatility"] = returns.groupby(_segments(frame)).transform(
        lambda s: s.rolling(k - 1).std(ddof=0)
    )
    volume_mean = groups.volume.transform(lambda s: s.rolling(k).mean())
    close_mean = groups.close.transform(lambda s: s.rolling(k).mean())
    features["volume_ratio"] = frame.volume / volume_mean.where(volume_mean != 0, 1)
    features["range_fraction"] = (frame.high - frame.low) / frame.close
    features["sma_distance"] = frame.close / close_mean - 1
    return features[FEATURE_NAMES]


def _training_samples(frame, config):
    frame = normalize_bars(frame).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    features = _feature_rows(frame, config.k)
    groups = frame.groupby(_segments(frame), sort=False)
    future_close, future_time = groups.close.shift(-1), groups.timestamp.shift(-1)
    valid = np.isfinite(features.to_numpy()).all(axis=1) & future_close.notna()
    labels = (future_close / frame.close - 1 > config.min_return_bps / 10_000).astype(int)
    info = frame[["symbol", "timestamp"]].copy()
    info["target_timestamp"] = future_time
    info["return_bps"] = (future_close / frame.close - 1) * 10000
    indices = info.loc[valid].sort_values(["timestamp", "symbol"]).index
    return (
        features.loc[indices].reset_index(drop=True),
        labels.loc[indices].reset_index(drop=True),
        info.loc[indices].reset_index(drop=True),
    )


def _window_features(bars, k):
    close = np.asarray([bar["close"] for bar in bars], dtype=float)
    volume = np.asarray([bar["volume"] for bar in bars], dtype=float)
    values = [close[-1] / close[-1 - lag] - 1 for lag in (1, max(1, k // 4), k // 2, k - 1)]
    values.extend(
        [
            np.std(close[1:] / close[:-1] - 1),
            volume[-1] / volume.mean() if volume.mean() > 0 else 0,
            (bars[-1]["high"] - bars[-1]["low"]) / close[-1],
            close[-1] / close.mean() - 1,
        ]
    )
    return np.asarray([values], dtype=float)


def _new_stats():
    return {
        "predictions": 0,
        "updates": 0,
        "vetoes": 0,
        "warmup_bars": 0,
        "evaluated_predictions": 0,
        "correct_predictions": 0,
        "accuracy": None,
        "brier_score": None,
        "log_loss": None,
        "baseline_accuracy": None,
        "baseline_brier_score": None,
        "baseline_log_loss": None,
        "return_mae_bps": None,
        "zero_return_mae_bps": None,
        "cost_vetoes": 0,
    }


class TimeSeriesModel:
    def __init__(self, config, estimator=None, scaler=None, metadata=None, regressor=None):
        self.config = config
        self.estimator = estimator
        self.regressor = regressor
        self.scaler = scaler
        self.metadata = metadata or {}
        self._states = {}
        self.audit = []
        self.stats = {**_new_stats(), "per_symbol": {}}

    def __getstate__(self):
        # A persisted model is always an offline initialization, never deployment memory.
        state = self.__dict__.copy()
        state["_states"] = {}
        state["audit"] = []
        state["stats"] = {**_new_stats(), "per_symbol": {}}
        return state

    def __setstate__(self, state):
        self.__init__(
            TimeSeriesConfig.model_validate(state["config"].model_dump()),
            state["estimator"],
            state["scaler"],
            state["metadata"],
            state.get("regressor"),
        )

    def checkpoint_state(self):
        """Explicit trusted-local checkpoint, including adapted weights and pending labels.

        Unlike pickling the model, this is a runtime snapshot. Keep it separate
        from the offline artifact used to initialize validation/test phases.
        """
        return copy.deepcopy(
            {
                "checkpoint_version": MODEL_VERSION,
                "config": self.config.model_dump(),
                "metadata": self.metadata,
                "offline_estimator": self.estimator,
                "offline_regressor": self.regressor,
                "scaler": self.scaler,
                "states": self._states,
                "stats": self.stats,
                "audit": self.audit,
            }
        )

    def _record(self, symbol, timestamp, allow, probability, reason, **extra):
        result = {"allow_entry": bool(allow), "probability": probability, "reason": reason, **extra}
        self.audit.append({"symbol": symbol, "timestamp": str(timestamp), **result})
        self.audit = self.audit[-500:]
        return result

    def predict(self, context):
        """Observe each completed minute once, learn matured labels, then predict next minute."""
        symbol, timestamp = context.get("symbol"), context.get("timestamp")
        if not self.config.enabled:
            return self._record(symbol, timestamp, True, None, "时序模型关闭")
        if self.estimator is None or self.scaler is None:
            return self._record(symbol, timestamp, False, None, "模型尚未训练")
        try:
            ts = pd.Timestamp(timestamp)
            bars = context["recent_bars"]
            if not isinstance(symbol, str) or not symbol or ts.tzinfo is None or pd.isna(ts):
                raise ValueError("invalid timestamp/symbol")
            if not isinstance(bars, list) or not bars:
                raise ValueError("missing bars")
            times = [pd.Timestamp(bar["timestamp"]) for bar in bars]
            if any(t.tzinfo is None or pd.isna(t) or t > ts for t in times) or times[-1] != ts:
                raise ValueError("future/stale bars")
            if any(b <= a for a, b in zip(times, times[1:], strict=False)):
                raise ValueError("unordered bars")
            bar = {key: float(bars[-1][key]) for key in ("open", "high", "low", "close", "volume")}
            if not all(math.isfinite(v) for v in bar.values()) or bar["volume"] < 0:
                raise ValueError("invalid numbers")
            if (
                not 0
                < bar["low"]
                <= min(bar["open"], bar["close"])
                <= max(bar["open"], bar["close"])
                <= bar["high"]
            ):
                raise ValueError("invalid prices")
            state = self._states.get(symbol)
            if state is None:
                state = {
                    "estimator": copy.deepcopy(self.estimator),
                    "regressor": copy.deepcopy(self.regressor),
                    "bars": deque(maxlen=self.config.k),
                    "last_time": None,
                    "count": 0,
                    "pending": None,
                    "stats": _new_stats(),
                }
                self._states[symbol] = state
                self.stats["per_symbol"][symbol] = state["stats"]
            last = state["last_time"]
            if last is not None and ts <= last:
                raise ValueError("replayed observation")
            contiguous = (
                last is not None
                and ts - last == pd.Timedelta(minutes=1)
                and (
                    ts.tz_convert("America/New_York").date()
                    == last.tz_convert("America/New_York").date()
                )
            )
            if not contiguous:
                state["bars"].clear()
                state["pending"] = None

            def count(name):
                self.stats[name] += 1
                state["stats"][name] += 1

            pending = state["pending"]
            updated = False
            if pending is not None:
                actual_return_bps = (bar["close"] / pending["close"] - 1) * 10000
                label = int(
                    bar["close"] / pending["close"] - 1 > self.config.min_return_bps / 10000
                )
                count("evaluated_predictions")
                if int(pending["probability"] >= 0.5) == label:
                    count("correct_predictions")
                balance = self.metadata.get("class_balance", {"0": 1, "1": 1})
                baseline = balance["1"] / (balance["0"] + balance["1"])
                probability = pending["probability"]

                def loss(prob):
                    prob = min(1 - 1e-15, max(1e-15, prob))
                    return -label * math.log(prob) - (1 - label) * math.log1p(-prob)

                scores = {
                    "brier_score": (probability - label) ** 2,
                    "log_loss": loss(probability),
                    "baseline_accuracy": int(int(baseline >= 0.5) == label),
                    "baseline_brier_score": (baseline - label) ** 2,
                    "baseline_log_loss": loss(baseline),
                }
                if pending.get("expected_return_bps") is not None:
                    scores["return_mae_bps"] = abs(
                        pending["expected_return_bps"] - actual_return_bps
                    )
                    scores["zero_return_mae_bps"] = abs(actual_return_bps)
                for tracker in (self.stats, state["stats"]):
                    n = tracker["evaluated_predictions"]
                    tracker["accuracy"] = tracker["correct_predictions"] / n
                    for name, score in scores.items():
                        average = tracker[name] or 0
                        tracker[name] = average + (score - average) / n
                if self.config.adapt:
                    with threadpool_limits(limits=1):
                        state["estimator"].partial_fit(pending["features"], [label])
                        if state["regressor"] is not None:
                            state["regressor"].partial_fit(
                                pending["features"], [np.clip(actual_return_bps / 100, -10, 10)]
                            )
                    count("updates")
                    updated = True
            state["last_time"] = ts
            state["count"] += 1
            state["bars"].append(bar)
            state["pending"] = None
            probability = None
            expected_return_bps = None
            if len(state["bars"]) >= self.config.k:
                features = self.scaler.transform(
                    _window_features(list(state["bars"]), self.config.k)
                )
                features = np.clip(features, -10, 10)
                with threadpool_limits(limits=1):
                    probability = float(state["estimator"].predict_proba(features)[0, 1])
                    if state["regressor"] is not None:
                        expected_return_bps = float(state["regressor"].predict(features)[0] * 100)
                        if not math.isfinite(expected_return_bps):
                            raise ValueError("invalid model return")
                if not math.isfinite(probability):
                    raise ValueError("invalid model probability")
                state["pending"] = {
                    "features": features,
                    "close": bar["close"],
                    "probability": probability,
                    "expected_return_bps": expected_return_bps,
                }
                count("predictions")
            warmup = state["count"] <= 2 * self.config.k or probability is None
            if warmup:
                count("warmup_bars")
            allow = not warmup and probability >= self.config.probability_threshold
            estimated_cost = context.get("round_trip_cost_bps")
            required_edge = None
            cost_veto = False
            if self.config.cost_aware and not warmup:
                if (
                    estimated_cost is None
                    or not math.isfinite(estimated_cost)
                    or estimated_cost < 0
                ):
                    cost_veto = True
                else:
                    required_edge = (
                        estimated_cost * self.config.cost_multiplier + self.config.min_edge_bps
                    )
                    cost_veto = expected_return_bps is None or expected_return_bps <= required_edge
                if allow and cost_veto:
                    count("cost_vetoes")
                allow = allow and not cost_veto
            if not allow:
                count("vetoes")
            reason = (
                "前2k周期适应/窗口收集，禁止模型交易"
                if warmup
                else (
                    "预期收益未覆盖成本门槛"
                    if cost_veto
                    else ("时序概率达到门槛" if allow else "时序概率低于门槛")
                )
            )
            return self._record(
                symbol,
                ts,
                allow,
                None if warmup else probability,
                reason,
                expected_return_bps=None if warmup else expected_return_bps,
                round_trip_cost_bps=estimated_cost,
                required_edge_bps=required_edge,
                observed_count=state["count"],
                warmup=warmup,
                updated=updated,
            )
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            return self._record(symbol, timestamp, False, None, "时间边界、顺序或行情无效")


def train_model(frame, config):
    features, labels, info = _training_samples(frame, config)
    eligible = len(features)
    if eligible < config.min_training_samples:
        raise ValueError(f"有效训练样本不足：{eligible}，至少需要{config.min_training_samples}")
    stride = max(1, math.ceil(eligible / MAX_TRAINING_SAMPLES))
    features, labels, info = features.iloc[::stride], labels.iloc[::stride], info.iloc[::stride]
    balance = {str(label): int((labels == label).sum()) for label in (0, 1)}
    if min(balance.values()) < 20:
        raise ValueError("正负两类各需至少20条训练标签")
    scaler = StandardScaler().fit(features.to_numpy())
    values = np.clip(scaler.transform(features.to_numpy()), -10, 10)
    estimator = SGDClassifier(
        loss="log_loss",
        learning_rate="constant",
        eta0=config.online_learning_rate,
        random_state=17,
        shuffle=False,
    )
    with threadpool_limits(limits=1):
        for _ in range(config.max_iter):
            for start in range(0, len(values), 256):
                estimator.partial_fit(
                    values[start : start + 256],
                    labels.iloc[start : start + 256],
                    classes=np.array([0, 1]),
                )
    regressor = SGDRegressor(
        loss="huber",
        epsilon=0.1,
        learning_rate="constant",
        eta0=config.online_learning_rate,
        random_state=17,
        shuffle=False,
    )
    targets = np.clip(info.return_bps.to_numpy() / 100, -10, 10)
    with threadpool_limits(limits=1):
        for _ in range(config.max_iter):
            for start in range(0, len(values), 256):
                regressor.partial_fit(values[start : start + 256], targets[start : start + 256])
    timestamps = pd.to_datetime(frame.timestamp, utc=True, format="mixed")
    metadata = {
        "train_start": timestamps.min().isoformat(),
        "train_end": timestamps.max().isoformat(),
        "sample_count": len(features),
        "eligible_sample_count": eligible,
        "sampling_stride": stride,
        "class_balance": balance,
        "symbols": sorted(frame.symbol.astype(str).str.upper().unique().tolist()),
        "feature_names": FEATURE_NAMES.copy(),
        "model_version": MODEL_VERSION,
        "sklearn_version": sklearn_version,
        "config": config.model_dump(),
        "last_sample_time": info.timestamp.max().isoformat(),
        "last_target_time": info.target_timestamp.max().isoformat(),
        "training_only": True,
        "mechanism": "offline frozen scaler; per-symbol online SGD; "
        "matured next-minute labels only; first 2k observations veto; gap resets window",
    }
    return TimeSeriesModel(config, estimator, scaler, metadata, regressor)
