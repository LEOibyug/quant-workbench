"""Frozen execution-policy confirmation against existing legacy high52 results."""

import hashlib
import json
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from quant_workbench.daily_strategies import cost_aware_targets
from quant_workbench.position import PositionConfig, simulate_positions
from study_annual_momentum import forecasts
from study_cost_execution import identity_targets
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    source = Path("artifacts/research/annual-momentum/random10-temporal.parquet")
    baseline = json.loads((ROOT / "2026-09-21-high52-temporal.json").read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == baseline["metadata"]["sha256"]
    frame = pd.read_parquet(source)
    windows = [
        ("2022-09-01", "2023-09-01"),
        ("2023-09-01", "2024-09-01"),
        ("2024-09-01", "2025-09-01"),
        ("2022-09-01", "2025-09-01"),
    ]
    results = []
    dest = ROOT / "2026-09-21-cost-execution-temporal.json"
    for start, end in windows:
        prior = sorted(frame.loc[frame.day < start, "day"].unique())[-273:]
        assert len(prior) == 273
        segment = frame[(frame.day >= prior[0]) & (frame.day < end)]
        mapping = forecasts(segment)["high52"]
        for policy in ("pooled_only", "cost_aware"):
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
                config = PositionConfig(
                    **{
                        **cfg,
                        "costs": costs,
                        "portfolio_policy": "cost_aware",
                        "rebalance_days": 20,
                    }
                )
                statuses = Counter()

                def track(*args, statuses=statuses):
                    weights, diagnostic = cost_aware_targets(*args)
                    statuses[diagnostic["status"]] += 1
                    return weights, diagnostic

                with ExitStack() as stack:
                    stack.enter_context(
                        patch("quant_workbench.position.daily_forecasts", return_value=mapping)
                    )
                    stack.enter_context(
                        patch(
                            "quant_workbench.position.cost_aware_targets",
                            side_effect=identity_targets if policy == "pooled_only" else track,
                        )
                    )
                    r = simulate_positions(segment, config, start, end, daily_bars=True)
                results.append(
                    dict(
                        start=start,
                        end_exclusive=end,
                        signal="high52",
                        execution=policy,
                        cost_multiplier=mult,
                        config=r["config"],
                        metrics=r["metrics"],
                        optimizer_status=dict(statuses),
                        contributions=r["contributions"],
                        curve=r["curve"],
                    )
                )
                save_results(dest, results)
                print(
                    start,
                    end,
                    policy,
                    mult,
                    r["metrics"]["return_pct"],
                    r["metrics"]["max_drawdown_pct"],
                    flush=True,
                )
    save_results(dest, results, completed=True)


if __name__ == "__main__":
    main()
