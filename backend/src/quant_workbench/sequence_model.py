"""Dual-scale causal convolution/GRU with delayed supervised replay and portable weights."""

import copy
import os
from collections import deque

import numpy as np
import pandas as pd
import torch
from sklearn import __version__ as sklearn_version
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.nn import functional as F

from quant_workbench.market_data import normalize_bars
from quant_workbench.sequence_features import SequenceHistory, stack_samples
from quant_workbench.timeseries import HistoricalContext, TimeSeriesModel, feedback_features

SEQUENCE_VERSION = "causal-conv-dual-gru-v1"
MAX_SEQUENCE_SAMPLES = 50000


def select_device():
    requested = os.environ.get("QUANT_TORCH_DEVICE", "auto").lower()
    available = {
        "cpu": True,
        "cuda": torch.cuda.is_available(),
        "mps": torch.backends.mps.is_available(),
    }
    if requested == "auto":
        return next(name for name in ("cuda", "mps", "cpu") if available[name])
    if requested not in available or not available[requested]:
        raise ValueError(f"设备 {requested} 不可用；可指定 auto/cpu/cuda/mps")
    return requested


class SequenceNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv1d(7, 32, 3)
        self.conv2 = nn.Conv1d(32, 32, 3, dilation=2)
        self.short_gru = nn.GRU(32, 64, num_layers=2, batch_first=True)
        self.long_gru = nn.GRU(7, 32, batch_first=True)
        self.short_attention = nn.Linear(64, 1)
        self.long_attention = nn.Linear(32, 1)
        self.context = nn.Sequential(nn.Linear(12, 32), nn.Tanh())
        self.fusion = nn.Sequential(nn.Linear(128, 64), nn.LayerNorm(64), nn.GELU())
        self.classifier = nn.Linear(64, 1)
        self.regressor = nn.Linear(64, 1)

    def forward(self, short, long, length, context):
        x = short.transpose(1, 2)
        x = F.gelu(self.conv1(F.pad(x, (2, 0))))
        x = F.gelu(self.conv2(F.pad(x, (4, 0))))
        short_states, _ = self.short_gru(x.transpose(1, 2))
        long_states, _ = self.long_gru(long)
        a = torch.softmax(self.short_attention(short_states), dim=1)
        mask = torch.arange(long.shape[1], device=long.device)[None, :] >= length[:, None]
        logits = self.long_attention(long_states).squeeze(-1).masked_fill(mask, -1e4)
        b = torch.softmax(logits, dim=1).unsqueeze(-1)
        fused = self.fusion(
            torch.cat(
                [(a * short_states).sum(1), (b * long_states).sum(1), self.context(context)], dim=1
            )
        )
        return self.classifier(fused).squeeze(-1), self.regressor(fused).squeeze(-1)


def cpu_tree(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {k: cpu_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [cpu_tree(v) for v in value]
    if isinstance(value, tuple):
        return tuple(cpu_tree(v) for v in value)
    return value


class SequenceEstimator:
    """A joint classifier/regressor; replay stores only fully matured causal samples."""

    def __init__(self, config, scalers, weights=None):
        self.config, self.scalers = config, scalers
        self.device = select_device()
        torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            self.network = SequenceNetwork()
        if weights is not None:
            self.network.load_state_dict(weights)
        self.network.to(self.device)
        self.optimizer = torch.optim.AdamW(
            self.network.parameters(), lr=config.neural_online_learning_rate, weight_decay=0.01
        )
        self.replay = deque(maxlen=config.replay_size)
        self.matured = 0

    def __getstate__(self):
        return dict(
            config=self.config,
            scalers=self.scalers,
            weights=cpu_tree(self.network.state_dict()),
            optimizer=cpu_tree(self.optimizer.state_dict()),
            replay=copy.deepcopy(self.replay),
            matured=self.matured,
        )

    def __setstate__(self, state):
        self.__init__(state["config"], state["scalers"], state["weights"])
        self.optimizer.load_state_dict(state["optimizer"])
        self.replay, self.matured = state["replay"], state["matured"]

    def prepare(self, batch):
        result = {}
        for key in ("short", "long"):
            shape = batch[key].shape
            scaled = self.scalers[key].transform(batch[key].reshape(-1, 7)).reshape(shape)
            scaled = np.clip(scaled, -8, 8).astype(np.float32)
            if key == "long":
                mask = np.arange(shape[1])[None, :] >= batch["length"][:, None]
                scaled[mask] = 0
            result[key] = torch.from_numpy(scaled).to(self.device)
        context = batch["context"].copy()
        context[:, :6] = np.clip(self.scalers["context"].transform(context[:, :6]), -8, 8)
        result["context"] = torch.from_numpy(context.astype(np.float32)).to(self.device)
        result["length"] = torch.from_numpy(batch["length"]).to(self.device)
        return result

    def predict_batch(self, batch):
        self.network.eval()
        with torch.no_grad():
            logits, returns = self.network(**self.prepare(batch))
            return torch.sigmoid(logits).cpu().numpy(), returns.cpu().numpy() * 100

    def predict(self, features):
        probability, returns = self.predict_batch(stack_samples([features]))
        return float(probability[0]), float(returns[0])

    def fit_batch(self, batch, labels, returns, optimizer):
        self.network.train()
        optimizer.zero_grad(set_to_none=True)
        logits, predicted = self.network(**self.prepare(batch))
        labels = torch.as_tensor(labels, dtype=torch.float32, device=self.device)
        target = torch.as_tensor(
            np.clip(np.asarray(returns) / 100, -10, 10), dtype=torch.float32, device=self.device
        )
        loss = F.binary_cross_entropy_with_logits(logits, labels) + F.huber_loss(
            predicted, target, delta=0.1
        )
        if not torch.isfinite(loss):
            raise ValueError("时序网络损失非有限数，停止本次训练")
        loss.backward()
        nn.utils.clip_grad_norm_(self.network.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()

    def update(self, features, label, returns):
        self.replay.append((copy.deepcopy(features), label, returns))
        self.matured += 1
        if self.matured % self.config.online_batch_size:
            return False
        indices = np.linspace(
            0, len(self.replay) - 1, min(len(self.replay), self.config.online_batch_size), dtype=int
        )
        samples = [self.replay[i] for i in indices]
        self.fit_batch(
            stack_samples([s[0] for s in samples]),
            [s[1] for s in samples],
            [s[2] for s in samples],
            self.optimizer,
        )
        return True


class SequenceModel(TimeSeriesModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sequence_seed = {}

    def __getstate__(self):
        state = super().__getstate__()
        state["_sequence_seed"] = {}
        return state

    def seed_history(self, frame, before):
        super().seed_history(frame, before)
        self._sequence_seed = {}
        cutoff = pd.Timestamp(before, tz="America/New_York").tz_convert("UTC")
        for symbol, group in frame[frame.timestamp < cutoff].groupby("symbol"):
            memory = SequenceHistory(self.config.k)
            for bar in group.sort_values("timestamp").tail(7801).to_dict("records"):
                memory.observe(bar, bar["timestamp"])
            self._sequence_seed[symbol] = memory

    def _observe_features(self, state, bar, ts, symbol):
        if "sequence" not in state:
            state["sequence"] = self._sequence_seed.pop(symbol, SequenceHistory(self.config.k))
        state["sequence"].observe(bar, ts)
        self.stats["runtime_device"] = state["estimator"].device

    def _build_features(self, state, memory):
        return state["sequence"].snapshot(memory.features(), state["feedback"])

    def _predict_heads(self, state, features):
        return state["estimator"].predict(features)

    def _update_heads(self, state, features, label, actual_return_bps):
        return state["estimator"].update(features, label, actual_return_bps)


def training_sequences(frame, config):
    frame = normalize_bars(frame).sort_values(["symbol", "timestamp"])
    samples, info = [], []
    stride = max(1, int(np.ceil(len(frame) / MAX_SEQUENCE_SAMPLES)))
    observed = 0
    for symbol, group in frame.groupby("symbol", sort=True):
        memory, sequence = HistoricalContext(), SequenceHistory(config.k)
        pending = deque()
        last = None
        segment = 0
        for bar in group.to_dict("records"):
            ts = bar["timestamp"]
            if (
                last is None
                or ts - last != pd.Timedelta(minutes=1)
                or (
                    ts.tz_convert("America/New_York").date()
                    != last.tz_convert("America/New_York").date()
                )
            ):
                pending.clear()
                segment += 1
            while pending and pending[0]["due"] <= ts:
                old = pending.popleft()
                returns = (bar["close"] / old["close"] - 1) * 10000
                samples.append(old["sample"])
                info.append(
                    dict(
                        symbol=symbol,
                        segment=old["segment"],
                        timestamp=old["time"],
                        target_timestamp=ts,
                        return_bps=returns,
                        label=int(returns > config.min_return_bps),
                    )
                )
            memory.observe(bar, ts)
            sequence.observe(bar, ts)
            observed += 1
            if len(sequence.short) == config.k and observed % stride == 0:
                pending.append(
                    dict(
                        time=ts,
                        segment=segment,
                        due=ts + pd.Timedelta(minutes=config.horizon),
                        close=bar["close"],
                        sample=sequence.snapshot(memory.features(), np.zeros((1, 6))),
                    )
                )
            last = ts
    if len(samples) < config.min_training_samples:
        raise ValueError("有效序列训练样本不足")
    info = pd.DataFrame(info)
    order = info.sort_values(["timestamp", "symbol"]).index.to_numpy()
    return stack_samples([samples[i] for i in order]), info.loc[order].reset_index(drop=True)


def train_sequence_model(frame, config):
    values, info = training_sequences(frame, config)
    boundary = info.iloc[int(len(info) * 0.6)].timestamp
    bootstrap = np.flatnonzero((info.target_timestamp < boundary).to_numpy())
    feedback_ids = np.flatnonzero((info.timestamp >= boundary).to_numpy())
    labels, returns = info.label.to_numpy(), info.return_bps.to_numpy()
    if min(int((labels[bootstrap] == c).sum()) for c in (0, 1)) < 20:
        raise ValueError("序列模型早期训练段正负标签各需20条")
    long_values = values["long"][bootstrap]
    valid_long = np.arange(long_values.shape[1])[None, :] < values["length"][bootstrap, None]
    scalers = {
        "short": StandardScaler().fit(values["short"][bootstrap].reshape(-1, 7)),
        "long": StandardScaler().fit(long_values[valid_long]),
        "context": StandardScaler().fit(values["context"][bootstrap, :6]),
    }
    estimator = SequenceEstimator(config, scalers)
    offline_optimizer = torch.optim.AdamW(
        estimator.network.parameters(), lr=config.neural_learning_rate, weight_decay=0.01
    )

    def fit(indices):
        for _ in range(config.max_iter):
            for start in range(0, len(indices), 128):
                ids = indices[start : start + 128]
                estimator.fit_batch(
                    {k: v[ids] for k, v in values.items()},
                    labels[ids],
                    returns[ids],
                    offline_optimizer,
                )

    fit(bootstrap)
    probabilities, predictions = np.zeros(len(info)), np.zeros(len(info))
    # The frozen teacher sees no feedback-period labels; batching does not cross sample windows.
    for start in range(0, len(feedback_ids), 256):
        ids = feedback_ids[start : start + 256]
        probabilities[ids], predictions[ids] = estimator.predict_batch(
            {k: v[ids] for k, v in values.items()}
        )
    pending, latest, last_segment = {}, {}, {}
    for i in feedback_ids:
        row = info.iloc[i]
        queue = pending.setdefault(row.symbol, deque())
        if last_segment.get(row.symbol) != row.segment:
            queue.clear()
            latest[row.symbol] = np.zeros((1, 6))
        while queue and info.iloc[queue[0]].target_timestamp <= row.timestamp:
            old = queue.popleft()
            latest[row.symbol] = feedback_features(
                probabilities[old], predictions[old], labels[old], returns[old]
            )
        values["context"][i, -6:] = latest[row.symbol][0]
        queue.append(i)
        last_segment[row.symbol] = row.segment
    fit(feedback_ids)
    metadata = dict(
        model_version=SEQUENCE_VERSION,
        sklearn_version=sklearn_version,
        torch_version=torch.__version__.split("+")[0],
        training_device=estimator.device,
        architecture="causal Conv1D(32) + GRU(64x2) / GRU(32) + attention + dual heads",
        parameter_count=sum(p.numel() for p in estimator.network.parameters()),
        train_start=frame.timestamp.min().isoformat(),
        train_end=frame.timestamp.max().isoformat(),
        teacher_last_target_time=info.iloc[bootstrap].target_timestamp.max().isoformat(),
        feedback_first_input_time=info.iloc[feedback_ids].timestamp.min().isoformat(),
        last_target_time=info.target_timestamp.max().isoformat(),
        sample_count=len(info),
        sampling_stride=max(1, int(np.ceil(len(frame) / MAX_SEQUENCE_SAMPLES))),
        feedback_nonzero_samples=int(values["context"][feedback_ids, -1].sum()),
        feature_names=[
            "minute_sequence_7",
            "completed_5minute_sequence_7",
            "background_6",
            "feedback_6",
        ],
        class_balance={str(c): int((labels == c).sum()) for c in (0, 1)},
        config=config.model_dump(),
        training_only=True,
    )
    # Offline artifact starts with empty replay and fresh online optimizer; no training memory.
    estimator.replay.clear()
    return SequenceModel(config, estimator, scalers, metadata)
