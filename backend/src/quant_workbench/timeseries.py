"""Offline initialization and causal online price/volume learning, without network calls."""

import copy
import math
from collections import deque
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from sklearn import __version__ as sklearn_version
from sklearn.kernel_approximation import RBFSampler
from sklearn.linear_model import SGDClassifier, SGDRegressor
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from quant_workbench.market_data import normalize_bars

MODEL_VERSION = "online-v3-multiscale-feedback"
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
    horizon: Literal[1, 5, 15] = 1
    architecture: Literal["linear", "rbf", "mlp", "gru"] = "linear"
    neural_learning_rate: float = Field(default=0.0003, ge=0.000001, le=0.01)
    neural_online_learning_rate: float = Field(default=0.00003, ge=0.000001, le=0.001)
    online_batch_size: int = Field(default=16, ge=1, le=64)
    replay_size: int = Field(default=512, ge=64, le=2048)
    rbf_components: int = Field(default=64, ge=16, le=256)
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


LONG_FEATURE_NAMES = [
    "session_return_1d",
    "session_return_5d",
    "session_return_20d",
    "volatility_1d",
    "volatility_5d",
    "volume_ratio_1d",
]


def _long_rows(frame):
    # Chain within-session returns, excluding overnight gaps and split jumps.
    previous = frame.groupby(_segments(frame), sort=False).close.shift(1)
    returns = np.log(frame.close / previous.fillna(frame.open))
    output = pd.DataFrame(index=frame.index)
    for name, width in zip(LONG_FEATURE_NAMES[:3], (390, 1950, 7800), strict=True):
        output[name] = returns.groupby(frame.symbol).transform(
            lambda values, width=width: values.rolling(width, min_periods=1).sum()
        )
    for name, width in zip(LONG_FEATURE_NAMES[3:5], (390, 1950), strict=True):
        output[name] = returns.groupby(frame.symbol).transform(
            lambda values, width=width: values.rolling(width, min_periods=1).std(ddof=0)
        )
    volume_mean = frame.groupby("symbol").volume.transform(
        lambda values: values.rolling(390, min_periods=1).mean()
    )
    output[LONG_FEATURE_NAMES[-1]] = frame.volume / volume_mean.where(volume_mean > 0, 1)
    return output


class HistoricalContext:
    """Bounded causal memory, shared feature definition for warm start and streaming."""

    def __init__(self):
        self.returns = deque(maxlen=7800)
        self.volumes = deque(maxlen=390)
        self.last_time = None
        self.last_close = None

    def observe(self, bar, timestamp):
        ts = pd.Timestamp(timestamp)
        if self.last_time is not None and ts <= self.last_time:
            raise ValueError("historical context must precede observation")
        contiguous = (
            self.last_time is not None
            and ts - self.last_time == pd.Timedelta(minutes=1)
            and ts.tz_convert("America/New_York").date()
            == self.last_time.tz_convert("America/New_York").date()
        )
        base = self.last_close if contiguous else bar["open"]
        self.returns.append(math.log(bar["close"] / base))
        self.volumes.append(bar["volume"])
        self.last_time, self.last_close = ts, bar["close"]

    def features(self):
        values = np.asarray(self.returns)
        volumes = np.asarray(self.volumes)
        return np.array(
            [
                [
                    *(values[-n:].sum() for n in (390, 1950, 7800)),
                    values[-390:].std(),
                    values[-1950:].std(),
                    volumes[-1] / volumes.mean() if volumes.mean() > 0 else 0,
                ]
            ]
        )


def _training_samples(frame, config):
    frame = normalize_bars(frame).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    features = _feature_rows(frame, config.k)
    if config.architecture != "linear":
        features = pd.concat([features, _long_rows(frame)], axis=1)
    groups = frame.groupby(_segments(frame), sort=False)
    future_close = groups.close.shift(-config.horizon)
    future_time = groups.timestamp.shift(-config.horizon)
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
    def __init__(
        self, config, estimator=None, scaler=None, metadata=None, regressor=None, mapper=None
    ):
        self.mapper = mapper
        self._history = {}
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
        state["_history"] = {}
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
            state.get("mapper"),
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
                "mapper": self.mapper,
                "history": self._history,
                "states": self._states,
                "stats": self.stats,
                "audit": self.audit,
            }
        )

    def seed_history(self, frame, before):
        """Read only pre-phase prices; never update weights or consume runtime warmup."""
        cutoff = pd.Timestamp(before, tz="America/New_York").tz_convert("UTC")
        if self._states:
            raise ValueError("seed history before runtime only")
        self._history = {}
        history = frame[frame.timestamp < cutoff].sort_values(["symbol", "timestamp"])
        for symbol, group in history.groupby("symbol"):
            memory = HistoricalContext()
            for bar in group.tail(7801).to_dict("records"):
                memory.observe(bar, bar["timestamp"])
            self._history[symbol] = memory

    def _transform(self, features):
        scaled = np.clip(self.scaler.transform(features), -10, 10)
        if self.mapper is None:
            return scaled
        return np.concatenate([scaled, self.mapper.transform(scaled)], axis=1)

    def _observe_features(self, state, bar, ts, symbol):
        pass

    def _build_features(self, state, memory):
        raw = _window_features(list(state["bars"]), self.config.k)
        if self.config.architecture != "linear":
            raw = np.concatenate([raw, memory.features()], axis=1)
        features = self._transform(raw)
        if self.config.architecture == "mlp":
            features = np.concatenate([features, state["feedback"]], axis=1)
        return features

    def _predict_heads(self, state, features):
        with threadpool_limits(limits=1):
            probability = float(state["estimator"].predict_proba(features)[0, 1])
            expected = (
                float(state["regressor"].predict(features)[0] * 100)
                if state["regressor"] is not None
                else None
            )
        return probability, expected

    def _update_heads(self, state, features, label, actual_return_bps):
        with threadpool_limits(limits=1):
            state["estimator"].partial_fit(features, [label])
            if state["regressor"] is not None:
                state["regressor"].partial_fit(
                    features, [np.clip(actual_return_bps / 100, -10, 10)]
                )
        return True

    def _record(self, symbol, timestamp, allow, probability, reason, **extra):
        result = {"allow_entry": bool(allow), "probability": probability, "reason": reason, **extra}
        self.audit.append({"symbol": symbol, "timestamp": str(timestamp), **result})
        self.audit = self.audit[-500:]
        return result

    def predict(self, context):
        """Observe once, learn matured labels, then predict the configured horizon."""
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
                    "pending": deque(),
                    "feedback": np.zeros((1, 6)),
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
                state["pending"].clear()
                state["feedback"] = np.zeros((1, 6))

            def count(name):
                self.stats[name] += 1
                state["stats"][name] += 1

            updated = False
            while state["pending"] and state["pending"][0]["due"] <= ts:
                pending = state["pending"].popleft()
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

                def loss(prob, label=label):
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
                state["feedback"] = feedback_features(
                    probability, pending.get("expected_return_bps") or 0, label, actual_return_bps
                )
                if self.config.adapt and self._update_heads(
                    state, pending["features"], label, actual_return_bps
                ):
                    count("updates")
                    updated = True
            state["last_time"] = ts
            state["count"] += 1
            state["bars"].append(bar)
            memory = self._history.setdefault(symbol, HistoricalContext())
            memory.observe(bar, ts)
            self._observe_features(state, bar, ts, symbol)
            probability = None
            expected_return_bps = None
            if len(state["bars"]) >= self.config.k:
                features = self._build_features(state, memory)
                probability, expected_return_bps = self._predict_heads(state, features)
                if expected_return_bps is not None and not math.isfinite(expected_return_bps):
                    raise ValueError("invalid model return")
                if not math.isfinite(probability):
                    raise ValueError("invalid model probability")
                state["pending"].append(
                    {
                        "due": ts + pd.Timedelta(minutes=self.config.horizon),
                        "features": features,
                        "close": bar["close"],
                        "probability": probability,
                        "expected_return_bps": expected_return_bps,
                    }
                )
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
                horizon=self.config.horizon,
                feedback=state["feedback"].ravel().tolist(),
            )
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            return self._record(symbol, timestamp, False, None, "时间边界、顺序或行情无效")


def feedback_features(probability, predicted_bps, label, actual_bps):
    return np.clip(
        [
            [
                probability - 0.5,
                label - 0.5,
                predicted_bps / 100,
                actual_bps / 100,
                (actual_bps - predicted_bps) / 100,
                1,
            ]
        ],
        -10,
        10,
    )


def _fit_heads(
    estimator, regressor, values, labels, targets, iterations, progress=None, stage="离线训练"
):
    with threadpool_limits(limits=1):
        for epoch in range(iterations):
            for start in range(0, len(values), 256):
                estimator.partial_fit(
                    values[start : start + 256],
                    labels[start : start + 256],
                    classes=np.array([0, 1]),
                )
                regressor.partial_fit(values[start : start + 256], targets[start : start + 256])
                if progress:
                    progress(
                        stage,
                        epoch * len(values) + min(start + 256, len(values)),
                        iterations * len(values),
                        "样本步",
                    )


def train_model(frame, config, progress=None):
    if progress:
        progress("构建因果特征与训练样本", 0, None, "")
    if config.architecture == "gru":
        try:
            from quant_workbench.sequence_model import train_sequence_model
        except ImportError as exc:
            raise ValueError("GRU需要PyTorch，请运行 uv sync --extra neural") from exc
        return train_sequence_model(frame, config, progress=progress)
    features, labels, info = _training_samples(frame, config)
    eligible = len(features)
    if eligible < config.min_training_samples:
        raise ValueError(f"有效训练样本不足：{eligible}，至少需要{config.min_training_samples}")
    stride = max(1, math.ceil(eligible / MAX_TRAINING_SAMPLES))
    features, labels, info = features.iloc[::stride], labels.iloc[::stride], info.iloc[::stride]
    labels = labels.to_numpy()
    balance = {str(label): int((labels == label).sum()) for label in (0, 1)}
    if min(balance.values()) < 20:
        raise ValueError("正负两类各需至少20条训练标签")
    # MLP feedback comes from a chronological teacher fitted only before the split.
    split = len(features)
    if config.architecture == "mlp":
        boundary = info.iloc[int(len(info) * 0.6)].timestamp
        bootstrap_mask = info.target_timestamp < boundary
        split = int(bootstrap_mask.sum())
        if split < 50 or min(int((labels[:split] == c).sum()) for c in (0, 1)) < 20:
            raise ValueError("MLP早期训练段正负标签各需20条")
    scaler = StandardScaler().fit(features.iloc[:split].to_numpy())
    values = np.clip(scaler.transform(features.to_numpy()), -10, 10)
    mapper = None
    if config.architecture == "rbf":
        mapper = RBFSampler(
            gamma=1 / values.shape[1], n_components=config.rbf_components, random_state=17
        ).fit(values)
        values = np.concatenate([values, mapper.transform(values)], axis=1)
    if config.architecture == "mlp":
        options = dict(
            hidden_layer_sizes=(64, 32),
            activation="tanh",
            alpha=0.01,
            learning_rate_init=config.online_learning_rate,
            random_state=17,
            shuffle=False,
            batch_size="auto",
        )
        estimator, regressor = MLPClassifier(**options), MLPRegressor(**options)
        values = np.concatenate([values, np.zeros((len(values), 6))], axis=1)
    else:
        estimator = SGDClassifier(
            loss="log_loss",
            learning_rate="constant",
            eta0=config.online_learning_rate,
            random_state=17,
            shuffle=False,
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
    _fit_heads(
        estimator,
        regressor,
        values[:split],
        labels[:split],
        targets[:split],
        config.max_iter,
        progress,
    )
    feedback_samples = 0
    if config.architecture == "mlp":
        # Purge boundary rows: teacher training labels must mature before any teacher input.
        if progress:
            progress("构建已成熟预测误差反馈", 0, None, "")
        eligible_feedback = np.flatnonzero((info.timestamp >= boundary).to_numpy())
        pending, feedback = {}, {}
        with threadpool_limits(limits=1):
            for i in eligible_feedback:
                row = info.iloc[i]
                queue = pending.setdefault(row.symbol, deque())
                prior = feedback.get(row.symbol, (None, np.zeros((1, 6))))
                day = row.timestamp.tz_convert("America/New_York").date()
                if prior[0] != day:
                    queue.clear()
                    prior = (day, np.zeros((1, 6)))
                while queue and queue[0]["due"] <= row.timestamp:
                    old = queue.popleft()
                    prior = (
                        day,
                        feedback_features(old["p"], old["r"], old["label"], old["actual"]),
                    )
                feedback[row.symbol] = prior
                values[i, -6:] = prior[1][0]
                p = float(estimator.predict_proba(values[i : i + 1])[0, 1])
                r = float(regressor.predict(values[i : i + 1])[0] * 100)
                queue.append(
                    dict(
                        due=row.target_timestamp,
                        p=p,
                        r=r,
                        label=labels[i],
                        actual=info.iloc[i].return_bps,
                    )
                )
            _fit_heads(
                estimator,
                regressor,
                values[eligible_feedback],
                labels[eligible_feedback],
                targets[eligible_feedback],
                config.max_iter,
                progress,
                "反馈阶段训练",
            )
        feedback_samples = len(eligible_feedback)
    timestamps = pd.to_datetime(frame.timestamp, utc=True, format="mixed")
    metadata = {
        "train_start": timestamps.min().isoformat(),
        "train_end": timestamps.max().isoformat(),
        "sample_count": split + feedback_samples,
        "eligible_sample_count": eligible,
        "sampling_stride": stride,
        "class_balance": balance,
        "symbols": sorted(frame.symbol.astype(str).str.upper().unique().tolist()),
        "feature_names": list(features.columns),
        "feedback_features": [
            "predicted_probability_centered",
            "realized_label_centered",
            "predicted_return_100bps",
            "realized_return_100bps",
            "error_100bps",
            "available",
        ]
        if config.architecture == "mlp"
        else [],
        "feedback_training_samples": feedback_samples,
        "transformed_features": values.shape[1],
        "model_version": MODEL_VERSION,
        "sklearn_version": sklearn_version,
        "config": config.model_dump(),
        "last_sample_time": info.timestamp.max().isoformat(),
        "last_target_time": info.target_timestamp.max().isoformat(),
        "training_only": True,
        "mechanism": "frozen training scaler; per-symbol online dual heads; "
        "matured horizon labels and error feedback; first 2k observations veto; gap resets window",
    }
    return TimeSeriesModel(config, estimator, scaler, metadata, regressor, mapper)
