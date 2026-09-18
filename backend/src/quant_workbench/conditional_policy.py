"""Frozen multi-scale pattern classifier: no future returns as training labels."""

import hashlib
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

ARTIFACT = Path(os.getenv("QUANT_PATTERN_POLICY", "artifacts/models/pattern-policy-v2/model.pt"))


def decompose(log_prices):
    y = np.asarray(log_prices, dtype=float)
    n = len(y)
    t = np.arange(n, dtype=float)
    centered = y - y.mean()
    trend_axis = t - t.mean()
    trend_axis /= np.linalg.norm(trend_axis)
    trend = trend_axis * (centered @ trend_axis)
    residual = centered - trend
    basis = np.column_stack(
        [fn(2 * np.pi * t / period) for period in (10, 21, 42) for fn in (np.sin, np.cos)]
    )
    basis -= basis.mean(axis=0)
    basis -= np.outer(trend_axis, trend_axis @ basis)
    q, _ = np.linalg.qr(basis)
    cycle = q @ (q.T @ residual)
    total = float(centered @ centered) + 1e-12
    trend_energy = float(trend @ trend) / total
    cycle_energy = max(0.0, float(cycle @ cycle) / total - 6 / n * (1 - trend_energy))
    pattern = np.array([trend_energy, cycle_energy, max(0.0, 1 - trend_energy - cycle_energy)])
    pattern /= pattern.sum()
    r = np.diff(y)
    vol = max(r.std(), 1e-6)
    # Orthogonal Haar-like adjacent block differences, not a claim of full CWT.
    haar = []
    for scale in (2, 4, 8, 16, 32):
        trimmed = centered[: n // scale * scale].reshape(-1, scale)
        differences = trimmed[:, : scale // 2].mean(1) - trimmed[:, scale // 2 :].mean(1)
        haar.append(float(np.mean(differences**2) / (np.var(centered) + 1e-12)))
    power = np.abs(np.fft.rfft(centered))[1:] ** 2
    periods = n / np.arange(1, len(power) + 1)
    bands = np.array(
        [
            power[periods <= 8].sum(),
            power[(periods > 8) & (periods <= 24)].sum(),
            power[periods > 24].sum(),
        ]
    ) / (power.sum() + 1e-12)
    spectral = np.r_[
        bands, haar, (y[-1] - y[0]) / (vol * np.sqrt(n)), (y[-1] - y.mean()) / max(y.std(), 1e-6)
    ]

    def smooth(window):
        cumulative = np.r_[0, np.cumsum(centered)]
        return np.array(
            [
                (cumulative[k + 1] - cumulative[max(0, k + 1 - window)]) / min(k + 1, window)
                for k in range(n)
            ]
        )

    channels = np.stack(
        [
            np.clip(np.r_[0, r] / vol, -8, 8),
            centered / max(y.std(), 1e-6),
            smooth(8) / max(y.std(), 1e-6),
            smooth(21) / max(y.std(), 1e-6),
        ]
    ).astype("float32")
    return channels, spectral.astype("float32"), pattern.astype("float32")


def network():
    import torch
    from torch import nn

    class PatternNet(nn.Module):
        def __init__(self):
            super().__init__()
            layers = []
            c = 4
            for dilation in (1, 2, 4):
                layers.extend([nn.Conv1d(c, 24, 3, padding=dilation, dilation=dilation), nn.GELU()])
                c = 24
            self.encoder = nn.Sequential(*layers)
            self.head = nn.Sequential(nn.Linear(24 + 10, 32), nn.GELU(), nn.Linear(32, 3))

        def forward(self, x, spectral):
            return self.head(torch.cat([self.encoder(x).mean(-1), spectral], dim=1))

    return PatternNet()


def artifact_digest():
    if not ARTIFACT.exists():
        raise ValueError("请先运行 train_pattern_policy.py 训练多尺度模式模型")
    return hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()


@lru_cache(maxsize=2)
def _load(path, modified):
    import torch

    torch.set_num_threads(min(torch.get_num_threads(), 4))
    bundle = torch.load(path, map_location="cpu", weights_only=False)
    model = network()
    model.load_state_dict(bundle["state"])
    model.eval()
    return model, bundle


def predict(channels, spectral):
    import torch

    artifact_digest()
    model, bundle = _load(str(ARTIFACT.resolve()), ARTIFACT.stat().st_mtime_ns)
    output = []
    with torch.no_grad():
        for start in range(0, len(channels), 512):
            logits = model(
                torch.from_numpy(channels[start : start + 512]),
                torch.from_numpy(spectral[start : start + 512]),
            )
            output.append(torch.softmax(logits, dim=1).numpy())
    return np.concatenate(output), bundle


def forecasts(daily, config):
    from sklearn.covariance import LedoitWolf

    prices = (
        daily.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    logs = np.log(prices.to_numpy())
    returns = np.diff(logs, axis=0)
    symbols = list(prices.columns)
    days = list(prices.index)
    inputs = []
    spectral = []
    teacher = []
    keys = []
    for i in range(63, len(days)):
        for j, _symbol in enumerate(symbols):
            x, f, y = decompose(logs[i - 63 : i + 1, j])
            inputs.append(x)
            spectral.append(f)
            teacher.append(y)
            keys.append((i, j))
    if not inputs:
        return {}
    if config.model == "spectral_rules":
        probabilities = np.stack(teacher)
        bundle = dict(version="spectral-rules-v2", cutoff="not-trained")
    else:
        probabilities, bundle = predict(np.stack(inputs), np.stack(spectral))
    probs = dict(zip(keys, probabilities, strict=True))
    out = {}
    for i in range(63, len(days)):
        history = returns[i - 63 : i]
        cov = LedoitWolf().fit(history).covariance_ + np.eye(len(symbols)) * 1e-12
        vol = np.sqrt(np.diag(cov))
        scores = np.zeros(len(symbols))
        for j, s in enumerate(symbols):
            p = probs[(i, j)]
            # Fixed interpretable mapping: upward trend or below local equilibrium.
            upward = logs[i, j] > logs[i - 20, j]
            window = logs[i - 20 : i + 1, j]
            z = (logs[i, j] - window.mean()) / max(window.std(ddof=1), 0.001)
            scores[j] = p[0] * upward + p[1] * (z < -0.5)
            out[(str(days[i]), s)] = dict(
                trend_probability=float(p[0]),
                reversion_probability=float(p[1]),
                noise_probability=float(p[2]),
                pattern_entropy=float(-np.sum(p * np.log(np.maximum(p, 1e-12))) / np.log(3)),
                classifier_version=bundle["version"],
                training_cutoff=bundle["cutoff"],
                observation_start=str(days[i - 63]),
                observation_end=str(days[i]),
                volatility=float(vol[j]),
                status="ok",
            )
        # Divide by total pool risk capacity so rejected/noisy stocks remain cash.
        inv = 1 / np.maximum(vol, 1e-6)
        raw = np.minimum(min(0.2, config.max_weight), 0.95 * inv / inv.sum() * scores)
        scale = min(1, 0.1 / max(float(np.sqrt(raw @ cov @ raw * 252)), 1e-12))
        raw *= scale
        for j, s in enumerate(symbols):
            out[(str(days[i]), s)].update(target_weight=float(raw[j]), risk_scale=scale)
    return out
