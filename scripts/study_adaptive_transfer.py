"""Unchanged adaptive specialist across all three previously evaluated pools."""

import json
from pathlib import Path

import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository

ROOT = Path("docs/research-results")


def main():
    original = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        x["config"]
        for x in original["results"]
        if x["method"] == "fixed_ensemble" and x["cost_multiplier"] == 1
    )
    pools = {
        "original20": Repository().load_dataset(original["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    output = ROOT / "2026-09-21-adaptive-transfer.json"
    for pool, frame in pools.items():
        for method in ("adaptive_specialist",):
            for multiplier in (1, 2):
                costs = dict(cfg["costs"])
                for key in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[key] *= multiplier
                config = PositionConfig(**{**cfg, "model": method, "costs": costs})
                run = simulate_positions(frame, config, "2025-09-01", "2026-09-01", daily_bars=True)
                row = dict(
                    pool=pool,
                    method=method,
                    cost_multiplier=multiplier,
                    config=run["config"],
                    metrics=run["metrics"],
                    contributions=run["contributions"],
                    first_halt=next((p["date"] for p in run["curve"] if p["halted"]), None),
                )
                results.append(row)
                output.write_text(json.dumps(dict(status="running", results=results), indent=2))
                print(
                    pool,
                    method,
                    multiplier,
                    round(run["metrics"]["return_pct"], 3),
                    round(run["metrics"]["max_drawdown_pct"], 3),
                    flush=True,
                )
    output.write_text(json.dumps(dict(status="completed", results=results), indent=2))


if __name__ == "__main__":
    main()
