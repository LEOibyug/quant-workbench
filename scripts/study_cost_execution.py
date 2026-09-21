"""Signal-fixed factorial comparison of funding/execution and target optimization."""

import json
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from quant_workbench.daily_strategies import cost_aware_targets, rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from study_annual_momentum import forecasts as annual_forecasts
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def identity_targets(symbols, returns, targets, current, cost_rates, cap, horizon):
    return targets.copy(), dict(
        status="identity_control",
        target_weights=targets.copy(),
        selected=[s for s in symbols if targets[s] > 0],
    )


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    results = []
    dest = ROOT / "2026-09-21-cost-execution.json"
    for pool, meta in manifest.items():
        frame = pd.read_parquet(meta["path"])
        maps = {
            "fixed_ensemble": rule_forecasts(frame, PositionConfig(**cfg)),
            "high52": annual_forecasts(frame)["high52"],
        }
        for signal, mapping in maps.items():
            for policy in ("legacy", "pooled_only", "cost_aware"):
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
                            "rebalance_days": 5 if signal == "fixed_ensemble" else 20,
                            "portfolio_policy": "legacy" if policy == "legacy" else "cost_aware",
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
                        if policy != "legacy":
                            stack.enter_context(
                                patch(
                                    "quant_workbench.position.cost_aware_targets",
                                    side_effect=identity_targets
                                    if policy == "pooled_only"
                                    else track,
                                )
                            )
                        r = simulate_positions(
                            frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                        )
                    results.append(
                        dict(
                            pool=pool,
                            signal=signal,
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
                        pool,
                        signal,
                        policy,
                        mult,
                        r["metrics"]["return_pct"],
                        r["metrics"]["max_drawdown_pct"],
                        r["metrics"]["trade_count"],
                        dict(statuses),
                        flush=True,
                    )
    save_results(dest, results, completed=True)


if __name__ == "__main__":
    main()
