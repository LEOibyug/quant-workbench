"""Generate matured executed-account marginal labels and fit a frozen ridge model."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from learned_applicability import prepare
from quant_workbench.conditional_policy import decompose
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from study_marginal_capital import exclude_targets

ROOT = Path("docs/research-results")


def main():
    source = Path("artifacts/models/conditional-policy-v2/history/daily.parquet")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    config = PositionConfig(**cfg)
    f = pd.read_parquet(source)
    f = f[f.day < "2025-09-01"]
    close, _, _ = prepare(f)
    f = f[f.day.isin(close.index)]
    symbols = list(close.columns)
    logs = np.log(close.to_numpy())
    returns = np.diff(logs, axis=0)
    mapping = rule_forecasts(f, config)
    prepared = {}
    for i in range(63, len(close)):
        day = str(close.index[i])
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(len(symbols)) * 1e-12
        w = np.array([mapping[day, s]["target_weight"] for s in symbols])
        prepared[i] = day, cov, w
    dest = ROOT / "2026-09-21-marginal-model-labels.json"
    groups = []
    if dest.exists():
        previous = json.loads(dest.read_text())
        if previous["source_sha256"] != source_sha or previous["config"] != cfg:
            raise ValueError("Checkpoint provenance mismatch")
        groups = previous["groups"]
    done = {g["signal_date"] for g in groups}
    for i in range(63, len(close) - 21, 21):
        day, cov, w = prepared[i]
        label_end = str(close.index[i + 21])
        split = (
            "train"
            if label_end < "2024-09-01"
            else ("validation" if str(close.index[i - 63]) >= "2024-09-01" else None)
        )
        if split is None or day in done:
            continue
        end = (pd.Timestamp(label_end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        segment = f[(f.day >= str(close.index[i - 63])) & (f.day < end)]

        def run(m, segment=segment, day=day, end=end):
            with patch("quant_workbench.position.daily_forecasts", return_value=m):
                return simulate_positions(segment, config, day, end, daily_bars=True)

        base_map = {k: v for k, v in mapping.items() if day <= k[0] < end}
        baseline = run(base_map)
        market = returns[i - 63 : i].mean(axis=1)
        h = returns[i - 63 : i] - returns[i - 63 : i].mean(axis=0)
        m = market - market.mean()
        beta = h.T @ m / max(m @ m, 1e-15)
        rows = []
        for j, symbol in enumerate(symbols):
            alt = {}
            for t in range(i, i + 22):
                date, c, w_t = prepared[t]
                target = exclude_targets(w_t, j, c, "redistribute")
                for k, s in enumerate(symbols):
                    alt[date, s] = {**mapping[date, s], "target_weight": float(target[k])}
            excluded = run(alt)
            assert all(p["positions"][symbol] == 0 for p in excluded["curve"])
            dr = baseline["metrics"]["return_pct"] - excluded["metrics"]["return_pct"]
            dd = baseline["metrics"]["max_drawdown_pct"] - excluded["metrics"]["max_drawdown_pct"]
            features = np.r_[
                decompose(logs[i - 63 : i + 1, j])[1], w[j], w.sum(), np.sqrt(cov[j, j]), beta[j]
            ]
            rows.append(
                dict(
                    symbol=symbol,
                    features=features.tolist(),
                    utility=dr - 0.5 * dd,
                    delta_return_pp=dr,
                    excluded_metrics=excluded["metrics"],
                )
            )
        groups.append(
            dict(
                signal_date=day,
                window_start=str(close.index[i - 63]),
                label_end=label_end,
                split=split,
                baseline_metrics=baseline["metrics"],
                rows=rows,
            )
        )
        dest.write_text(
            json.dumps(
                dict(status="running", source_sha256=source_sha, config=cfg, groups=groups),
                indent=2,
            )
        )
        print(split, day, label_end, len(groups), flush=True)
    arrays = {}
    for split in ("train", "validation"):
        rows = [r for g in groups if g["split"] == split for r in g["rows"]]
        arrays[split] = (
            np.array([r["features"] for r in rows]),
            np.array([r["utility"] for r in rows]),
        )
    x, y = arrays["train"]
    vx, vy = arrays["validation"]
    model = make_pipeline(StandardScaler(), Ridge(alpha=10)).fit(x, y)
    pred = model.predict(vx)
    artifact = Path("artifacts/models/marginal-model-v0/model.joblib")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact)
    report = dict(
        artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        feature_count=x.shape[1],
        train_windows=len(y),
        validation_windows=len(vy),
        train_mean=float(y.mean()),
        mse=float(np.mean((pred - vy) ** 2)),
        constant_mse=float(np.mean((y.mean() - vy) ** 2)),
        correlation=float(np.corrcoef(pred, vy)[0, 1]),
        positive_prediction_fraction=float(np.mean(pred > 0)),
        predicted_positive_actual_mean=float(vy[pred > 0].mean()) if (pred > 0).any() else None,
        predicted_nonpositive_actual_mean=float(vy[pred <= 0].mean())
        if (pred <= 0).any()
        else None,
        validation_predictions=pred.tolist(),
        validation_actual=vy.tolist(),
    )
    (ROOT / "2026-09-21-marginal-model-training.json").write_text(json.dumps(report, indent=2))
    dest.write_text(
        json.dumps(
            dict(status="completed", source_sha256=source_sha, config=cfg, groups=groups), indent=2
        )
    )
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}), flush=True)


if __name__ == "__main__":
    main()
