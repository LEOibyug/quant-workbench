"""Magnitude-aware expert utility training before the frozen boundary."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from learned_applicability import feature, prepare
from regime_router import utilities
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from utility_router import block_indices, choices, route_scores


def main():
    source = Path("artifacts/models/conditional-policy-v2/history/daily.parquet")
    f = pd.read_parquet(source)
    f = f[f.day.astype(str) < "2025-09-01"]
    close, opens, weights = prepare(f)
    logs = np.log(close.to_numpy())
    data = {"train": [], "validation": []}
    for i in range(63, len(close) - 22, 21):
        end = str(close.index[i + 22])
        split = (
            "train"
            if end < "2024-09-01"
            else (
                "validation"
                if str(close.index[i - 63]) >= "2024-09-01" and end < "2025-09-01"
                else None
            )
        )
        if split:
            x = np.array([feature(logs, weights, i, j) for j in range(close.shape[1])])
            y = np.array([utilities(opens, weights, i, j)[1:] for j in range(close.shape[1])])
            data[split].append((x, y, str(close.index[i - 63]), str(close.index[i]), end))
    x, y = [np.concatenate([row[k] for row in data["train"]]) for k in (0, 1)]
    scaler = StandardScaler().fit(x)
    z = scaler.transform(x)
    model = Ridge(alpha=10).fit(z, y)
    rng = np.random.default_rng(20250921)
    bootstrap = []
    for _ in range(100):
        groups = block_indices(len(data["train"]), rng)
        indices = np.concatenate(
            [np.arange(g * close.shape[1], (g + 1) * close.shape[1]) for g in groups]
        )
        bootstrap.append(Ridge(alpha=10).fit(z[indices], y[indices]))
    bundle = dict(scaler=scaler, model=model, bootstrap=bootstrap, mean_utility=y.mean(axis=0))
    vx, vy = [np.concatenate([row[k] for row in data["validation"]]) for k in (0, 1)]
    report = dict(
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        splits={},
        validation={},
        train_mean_utility=y.mean(axis=0).tolist(),
    )
    for name, rows in data.items():
        report["splits"][name] = dict(
            date_groups=len(rows),
            stock_windows=len(rows) * close.shape[1],
            first_window_start=min(r[2] for r in rows),
            last_signal=max(r[3] for r in rows),
            last_label_end=max(r[4] for r in rows),
        )
    for mode in ("mean", "lower", "constant"):
        scores = route_scores(bundle, vx, mode)
        chosen = choices(scores)
        actual = np.c_[np.zeros(len(vy)), vy][np.arange(len(vy)), chosen]
        report["validation"][mode] = dict(
            choice_counts=np.bincount(chosen, minlength=4).tolist(),
            mean_shadow_utility=float(actual.mean()),
            mean_squared_error=float(np.mean((scores - vy) ** 2)),
            note="lower分位不是均值预测，其MSE仅作描述",
        )
    root = Path("artifacts/models/utility-router-v0")
    root.mkdir(parents=True, exist_ok=True)
    artifact = root / "model.joblib"
    joblib.dump(bundle, artifact)
    report["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    Path("docs/research-results/2026-09-21-utility-router-training.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
