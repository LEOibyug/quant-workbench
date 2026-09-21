"""Evaluate both frozen classifiers through the original shared-cash engine."""

import json
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from learned_applicability import feature, prepare
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")


def mapping_for(close, weights, model):
    logs = np.log(close.to_numpy())
    returns = np.diff(logs, axis=0)
    mapping = {}
    for i in range(63, len(close)):
        features = np.array([feature(logs, weights, i, j) for j in range(len(close.columns))])
        probabilities = np.zeros((len(close.columns), 4))
        probabilities[:, model.classes_] = model.predict_proba(features)
        target = np.minimum(0.2, (probabilities[:, 1:] * weights[i]).sum(axis=1))
        target *= min(1, 0.95 / max(target.sum(), 1e-12))
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(len(target)) * 1e-12
        target *= min(1, 0.1 / max(np.sqrt(target @ cov @ target * 252), 1e-12))
        for j, symbol in enumerate(close.columns):
            mapping[str(close.index[i]), symbol] = dict(
                target_weight=float(target[j]), volatility=float(np.sqrt(cov[j, j])), status="ok"
            )
    return mapping


def main():
    original = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in original["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    pools = {
        "original20": Repository().load_dataset(original["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    out = ROOT / "2026-09-21-learned-applicability-transfer.json"
    for pool, frame in pools.items():
        close, _, weights = prepare(frame)
        for name in ("logistic", "hist_gradient"):
            model = joblib.load(f"artifacts/models/learned-applicability-v0/{name}.joblib")
            mapping = mapping_for(close, weights, model)
            for mult in (1, 2):
                costs = dict(cfg["costs"])
                for key in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[key] *= mult
                config = PositionConfig(**{**cfg, "costs": costs})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    run = simulate_positions(
                        frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                    )
                results.append(
                    dict(
                        pool=pool,
                        candidate=name,
                        cost_multiplier=mult,
                        config=run["config"],
                        metrics=run["metrics"],
                        contributions=run["contributions"],
                    )
                )
                out.write_text(json.dumps({"status": "running", "results": results}, indent=2))
                print(
                    pool,
                    name,
                    mult,
                    run["metrics"]["return_pct"],
                    run["metrics"]["max_drawdown_pct"],
                    flush=True,
                )
    out.write_text(json.dumps({"status": "completed", "results": results}, indent=2))


if __name__ == "__main__":
    main()
