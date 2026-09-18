"""Dual-scale causal convolution/GRU with delayed supervised replay and portable weights."""

import copy
import os
import warnings
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
from quant_workbench.timeseries import (
    TimeSeriesConfig,
    TimeSeriesModel,
    _long_rows,
    feedback_features,
)

SEQUENCE_VERSION = "causal-conv-dual-gru-v1"
MAX_SEQUENCE_SAMPLES = 50000


class _CudaPrediction:
    """Replay fixed-shape inference kernels while reading the current network weights."""

    def __init__(self, network, inputs):
        self.inputs = {key: value.clone() for key, value in inputs.items()}
        stream = torch.cuda.Stream()
        stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(stream):
            for _ in range(3):
                network(**self.inputs)
        torch.cuda.current_stream().wait_stream(stream)
        self.graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.graph):
            self.outputs = network(**self.inputs)

    def __call__(self, inputs):
        for key, value in inputs.items():
            self.inputs[key].copy_(value)
        self.graph.replay()
        return self.outputs


def select_device():
    requested = os.environ.get("QUANT_TORCH_DEVICE", "auto").lower()
    available = {"cpu": True, "cuda": torch.cuda.is_available()}
    if requested == "auto":
        return next(name for name in ("cuda", "cpu") if available[name])
    if requested not in available or not available[requested]:
        raise ValueError(f"设备 {requested} 不可用；已放弃MPS，面向CUDA，可指定 auto/cuda/cpu")
    return requested


def _best_temperature(labels, logits):
    """Grid-search the sigmoid temperature minimizing NLL; fitted on training-period labels only.

    Ties resolve towards 1.0 (no rescaling), so signal-free logits keep the identity.
    """
    labels = np.asarray(labels, dtype=np.float64)
    z = np.asarray(logits, dtype=np.float64)

    def nll(temperature):
        p = np.clip(1.0 / (1.0 + np.exp(-z / temperature)), 1e-12, 1 - 1e-12)
        return float(-(labels * np.log(p) + (1 - labels) * np.log1p(-p)).mean())

    best_temperature, best_nll = 1.0, nll(1.0)
    for temperature in np.geomspace(0.05, 4.0, 80):
        score = nll(temperature)
        if score < best_nll:
            best_temperature, best_nll = float(temperature), score
    return best_temperature


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

    def __init__(self, config, scalers, weights=None, return_scale=100.0):
        self.config = TimeSeriesConfig.model_validate(config.model_dump())
        self.scalers = scalers
        self.return_scale = float(return_scale)
        self.device = select_device()
        torch.set_num_threads(1)
        if self.device == "cuda":
            # 形状固定（batch=1在线/128离线），cudnn自动调优与TF32矩阵精度面向CUDA加速。
            torch.backends.cudnn.benchmark = True
            torch.set_float32_matmul_precision("high")
        self.temperature = 1.0
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            self.network = SequenceNetwork()
        if weights is not None:
            self.network.load_state_dict(weights)
        self.network.to(self.device)
        # 在线每根bar都要缩放特征；绕开StandardScaler.transform的输入校验开销，
        # 用等价的numpy广播运算（与sklearn逐位一致，见测试）。
        self._scale_params = {
            key: (scaler.mean_, scaler.scale_) for key, scaler in scalers.items()
        }
        self.optimizer = torch.optim.AdamW(
            self.network.parameters(), lr=config.neural_online_learning_rate, weight_decay=0.01
        )
        self.replay = deque(maxlen=config.replay_size)
        self.matured = 0
        # Runtime-only cache: never serialize CUDA graphs or their device buffers.
        self._cuda_prediction = None
        self._cuda_graph_enabled = (
            self.device == "cuda" and os.environ.get("QUANT_CUDA_GRAPHS", "1") != "0"
        )

    def __getstate__(self):
        return dict(
            config=self.config,
            return_scale=self.return_scale,
            scalers=self.scalers,
            weights=cpu_tree(self.network.state_dict()),
            optimizer=cpu_tree(self.optimizer.state_dict()),
            replay=copy.deepcopy(self.replay),
            matured=self.matured,
            temperature=self.temperature,
        )

    def __setstate__(self, state):
        self.__init__(
            state["config"], state["scalers"], state["weights"], state.get("return_scale", 100.0)
        )
        self.optimizer.load_state_dict(state["optimizer"])
        self.replay, self.matured = state["replay"], state["matured"]
        self.temperature = float(state.get("temperature", 1.0))

    def prepare(self, batch):
        result = {}
        for key in ("short", "long"):
            raw = batch[key]
            mean, scale = self._scale_params[key]
            scaled = (raw - mean.astype(raw.dtype)) / scale.astype(raw.dtype)
            scaled = np.clip(scaled, -8, 8)
            if scaled.dtype != np.float32:
                scaled = scaled.astype(np.float32)
            if key == "long":
                mask = np.arange(raw.shape[1])[None, :] >= batch["length"][:, None]
                scaled[mask] = 0
            result[key] = torch.from_numpy(scaled).to(self.device)
        context = batch["context"].copy()
        mean, scale = self._scale_params["context"]
        context[:, :6] = np.clip(
            (context[:, :6] - mean.astype(context.dtype)) / scale.astype(context.dtype), -8, 8
        )
        result["context"] = torch.from_numpy(context.astype(np.float32)).to(self.device)
        result["length"] = torch.from_numpy(batch["length"]).to(self.device)
        return result

    def predict_batch(self, batch):
        if self.network.training:
            self.network.eval()
        with torch.no_grad():
            inputs = self.prepare(batch)
            if self._cuda_graph_enabled and len(batch["short"]) == 1:
                # k is fixed per estimator. Updated AdamW weights keep the same storage,
                # so replay uses the latest online model, never stale predictions.
                if self._cuda_prediction is None:
                    try:
                        self._cuda_prediction = _CudaPrediction(self.network, inputs)
                    except RuntimeError as exc:
                        self._cuda_graph_enabled = False
                        warnings.warn(f"CUDA Graph 不可用，使用普通推理：{exc}", stacklevel=2)
                if self._cuda_prediction is not None:
                    logits, returns = self._cuda_prediction(inputs)
                else:
                    logits, returns = self.network(**inputs)
            else:
                logits, returns = self.network(**inputs)
            # 温度校准只在推理端生效；在线训练仍以未缩放logits计算损失。
            # Transfer both heads together rather than synchronizing twice per bar.
            heads = torch.stack((torch.sigmoid(logits / self.temperature), returns)).cpu().numpy()
            return heads[0], heads[1] * self.return_scale

    def eval_logits(self, batch):
        self.network.eval()
        with torch.no_grad():
            logits, _ = self.network(**self.prepare(batch))
        return logits.cpu().numpy()

    def predict(self, features):
        # 单样本快路径：视图加一维，避免stack_samples逐键np.stack复制。
        batch = {
            "short": features["short"][None],
            "long": features["long"][None],
            "length": features["length"][None],
            "context": features["context"][None],
        }
        probability, returns = self.predict_batch(batch)
        return float(probability[0]), float(returns[0])

    def fit_batch(self, batch, labels, returns, optimizer):
        prepared = self.prepare(batch)
        labels, target = self.prepare_targets(labels, returns)
        self.fit_prepared(prepared, labels, target, optimizer)

    def prepare_targets(self, labels, returns):
        labels = torch.as_tensor(labels, dtype=torch.float32, device=self.device)
        target = torch.as_tensor(
            np.clip(np.asarray(returns) / self.return_scale, -10, 10),
            dtype=torch.float32,
            device=self.device,
        )
        return labels, target

    def fit_prepared(self, batch, labels, target, optimizer):
        if not self.network.training:
            self.network.train()
        optimizer.zero_grad(set_to_none=True)
        logits, predicted = self.network(**batch)
        loss = F.binary_cross_entropy_with_logits(logits, labels) + F.huber_loss(
            predicted, target, delta=1.0 if self.config.return_normalization else 0.1
        )
        if not torch.isfinite(loss):
            raise ValueError("时序网络损失非有限数，停止本次训练")
        loss.backward()
        nn.utils.clip_grad_norm_(self.network.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()

    def update(self, features, label, returns):
        # 快照各数组替代deepcopy；样本入队后不再被就地修改，内容与deepcopy一致。
        self.replay.append(
            (
                {
                    key: (value.copy() if isinstance(value, np.ndarray) else copy.deepcopy(value))
                    for key, value in features.items()
                },
                label,
                returns,
            )
        )
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
    frame = normalize_bars(frame).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    # The same causal rolling background as streaming HistoricalContext, computed
    # once in pandas instead of copying up to 7,800 returns for every training bar.
    background = _long_rows(frame)
    samples, info = [], []
    stride = max(1, int(np.ceil(len(frame) / MAX_SEQUENCE_SAMPLES)))
    observed = 0
    for symbol, group in frame.groupby("symbol", sort=True):
        sequence = SequenceHistory(config.k)
        pending = deque()
        last = None
        segment = 0
        for bar, context in zip(
            group.to_dict("records"), background.loc[group.index].to_numpy(), strict=True
        ):
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
            sequence.observe(bar, ts)
            observed += 1
            if len(sequence.short) == config.k and observed % stride == 0:
                pending.append(
                    dict(
                        time=ts,
                        segment=segment,
                        due=ts + pd.Timedelta(minutes=config.horizon),
                        close=bar["close"],
                        sample=sequence.snapshot(context, np.zeros((1, 6))),
                    )
                )
            last = ts
    if len(samples) < config.min_training_samples:
        raise ValueError("有效序列训练样本不足")
    info = pd.DataFrame(info)
    order = info.sort_values(["timestamp", "symbol"]).index.to_numpy()
    return stack_samples([samples[i] for i in order]), info.loc[order].reset_index(drop=True)


def train_sequence_model(frame, config, progress=None):
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
    # Fit scaling exclusively before the purged teacher boundary, never validation/test.
    return_scale = (
        float(np.clip(np.std(returns[bootstrap]), 5, 200)) if config.return_normalization else 100.0
    )
    estimator = SequenceEstimator(config, scalers, return_scale=return_scale)
    offline_optimizer = torch.optim.AdamW(
        estimator.network.parameters(), lr=config.neural_learning_rate, weight_decay=0.01
    )

    def fit(indices, stage):
        # Reuse normalized device tensors across epochs, bounded by both a user cap
        # and available VRAM. Build afresh for the feedback stage after context changes.
        cache = None
        if estimator.device == "cuda" and config.max_iter > 1:
            budget = max(0, int(os.environ.get("QUANT_TRAIN_CACHE_MIB", "256"))) * 2**20
            budget = min(budget, torch.cuda.mem_get_info()[0] // 5)
            required = len(indices) * (
                sum(v[0].nbytes for v in values.values()) + 8
            )
            if required <= budget:
                cache = []
                for start in range(0, len(indices), 128):
                    ids = indices[start : start + 128]
                    cache.append((
                        estimator.prepare({k: v[ids] for k, v in values.items()}),
                        *estimator.prepare_targets(labels[ids], returns[ids]),
                    ))
        for epoch in range(config.max_iter):
            for start in range(0, len(indices), 128):
                ids = indices[start : start + 128]
                if cache is None:
                    estimator.fit_batch(
                        {k: v[ids] for k, v in values.items()},
                        labels[ids], returns[ids], offline_optimizer,
                    )
                else:
                    estimator.fit_prepared(*cache[start // 128], offline_optimizer)
                if progress:
                    progress(
                        stage,
                        epoch * len(indices) + min(start + 128, len(indices)),
                        config.max_iter * len(indices),
                        "样本步",
                    )

    fit(bootstrap, "GRU 初始阶段训练")
    if progress:
        progress("生成教师预测与成熟误差反馈", 0, None, "")
    probabilities, predictions = np.zeros(len(info)), np.zeros(len(info))
    # The frozen teacher sees no feedback-period labels; batching does not cross sample windows.
    for start in range(0, len(feedback_ids), 256):
        ids = feedback_ids[start : start + 256]
        probabilities[ids], predictions[ids] = estimator.predict_batch(
            {k: v[ids] for k, v in values.items()}
        )
    pending, latest, last_segment = {}, {}, {}
    # Avoid constructing pandas Series twice per sample in this causal CPU loop.
    rows = list(info.itertuples(index=False))
    for i in feedback_ids:
        row = rows[i]
        queue = pending.setdefault(row.symbol, deque())
        if last_segment.get(row.symbol) != row.segment:
            queue.clear()
            latest[row.symbol] = np.zeros((1, 6))
        while queue and rows[queue[0]].target_timestamp <= row.timestamp:
            old = queue.popleft()
            latest[row.symbol] = feedback_features(
                probabilities[old], predictions[old], labels[old], returns[old]
            )
        values["context"][i, -6:] = latest[row.symbol][0]
        queue.append(i)
        last_segment[row.symbol] = row.segment
    fit(feedback_ids, "GRU 反馈阶段训练")
    if progress:
        progress("开发期温度校准", 0, None, "")
    # 校准只用训练段已成熟标签：对最终网络的logits网格搜索温度，推理时概率更贴合经验频率。
    calibration_logits = np.zeros(len(info))
    for start in range(0, len(feedback_ids), 256):
        ids = feedback_ids[start : start + 256]
        calibration_logits[ids] = estimator.eval_logits({k: v[ids] for k, v in values.items()})
    estimator.temperature = _best_temperature(
        labels[feedback_ids], calibration_logits[feedback_ids]
    )
    metadata = dict(
        model_version=SEQUENCE_VERSION
        + ("-scaled-return-v2" if config.return_normalization else ""),
        return_scale_bps=return_scale,
        temperature=estimator.temperature,
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
