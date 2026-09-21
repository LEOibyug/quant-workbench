"""Execution cross-check of the predeclared long-only multiscale candidate."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from study_symmetric_trend import forecasts


def main():
    root = Path("docs/research-results")
    old = json.loads((root / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    pools = {
        "original20": Repository().load_dataset(old["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    for pool, frame in pools.items():
        fc = forecasts(frame, "long_only")
        mapping = {
            (d, s): dict(target_weight=w, volatility=0.01, status="ok")
            for d, weights in fc.items()
            for s, w in weights.items()
        }
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
                r = simulate_positions(frame, config, "2025-09-01", "2026-09-01", daily_bars=True)
            row = dict(
                pool=pool,
                cost_multiplier=mult,
                metrics=r["metrics"],
                contributions=r["contributions"],
                config=r["config"],
                candidate="multiscale_long_only_v0",
            )
            results.append(row)
            print(
                pool, mult, r["metrics"]["return_pct"], r["metrics"]["max_drawdown_pct"], flush=True
            )
    (root / "2026-09-21-multiscale-existing-engine.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
