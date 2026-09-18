"""Fixed before execution: compare allocation off/on, including doubled trading costs."""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from quant_workbench.allocation import AllocationConfig
from quant_workbench.engine import simulate
from quant_workbench.models import StrategyConfig
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository


def run(task):
    repo = Repository()
    frame = repo.load_dataset(task["dataset"])
    costs = StrategyConfig(**task["costs"])
    if task["horizon"] == "long":
        config = PositionConfig(
            model=task["model"], costs=costs, allocation=AllocationConfig(**task["allocation"])
        )
        result = simulate_positions(frame, config, task["start"], task["end"])
    else:
        config = StrategyConfig(
            **{**task["costs"], "strategy": task["model"], "allocation": task["allocation"]}
        )
        result = simulate(frame, config, task["start"], task["end"])
    curve = result.get("portfolio_curve", result["curve"])
    return dict(
        task=task,
        metrics=result["metrics"],
        contributions=result["contributions"],
        daily_returns=result["daily_returns"],
        average_cash_pct=sum(p.get("cash_weight", 0) for p in curve) / len(curve) * 100
        if "cash_weight" in curve[0]
        else None,
        allocation_statuses={
            status: sum(d["status"] == status for d in result.get("allocation_decisions", []))
            for status in {d["status"] for d in result.get("allocation_decisions", [])}
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    repo = Repository()
    periods = [
        ("68df84185f274ab78eae6cd08a0c19a8", "2025-03-03", "2025-09-01", "2025-10-31"),
        ("bb9c03c89e0c4415b9b0f141eae22d65", "2026-04-01", "2026-04-01", "2026-07-01"),
    ]
    tasks = []
    for dataset, long_start, short_start, end in periods:
        repo.get("datasets", dataset)
        for horizon, models, start in [
            ("long", ["trend", "equal_weight"], long_start),
            ("short", ["sma", "regime_adaptive"], short_start),
        ]:
            for model in models:
                for enabled in (False, True):
                    for multiplier in (1, 2):
                        cost = StrategyConfig().model_dump()
                        for field in (
                            "spread_bps",
                            "slippage_bps",
                            "commission_per_share",
                            "minimum_commission",
                            "sell_fee_bps",
                        ):
                            cost[field] *= multiplier
                        allocation = AllocationConfig(
                            enabled=enabled,
                            max_daily_turnover=0.2 if horizon == "long" else 1,
                        ).model_dump()
                        tasks.append(
                            dict(
                                dataset=dataset,
                                horizon=horizon,
                                model=model,
                                start=start,
                                end=end,
                                costs=cost,
                                allocation=allocation,
                                cost_multiplier=multiplier,
                            )
                        )
    protocol = dict(
        tasks=tasks,
        parameter_selection="fixed; no tuning based on these results",
        fresh_holdout=False,
        caution="Exposure and risk limits differ; returns alone do not prove alpha",
    )
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    summary = []
    with ProcessPoolExecutor(max_workers=2) as pool:
        for result in pool.map(run, tasks):
            summary.append(result)
            (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
            t, m = result["task"], result["metrics"]
            print(
                f"{t['horizon']} {t['model']} {t['start']} allocation={t['allocation']['enabled']} "
                f"cost={t['cost_multiplier']}x return={m['return_pct']:.3f}% "
                f"DD={m['max_drawdown_pct']:.3f}% fills={m['trade_count']}",
                flush=True,
            )


if __name__ == "__main__":
    main()
