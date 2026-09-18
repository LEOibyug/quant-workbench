"""Frozen seven-method comparison: no search, ranking, or adaptive candidate changes."""

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository

METHODS = [
    "trend",
    "equal_weight",
    "cross_momentum",
    "channel_trend",
    "residual_reversal",
    "minimum_variance",
    "fixed_ensemble",
]


def run(task):
    frame = Repository().load_dataset(task["dataset"])
    cfg = PositionConfig(**task["config"])
    result = simulate_positions(frame, cfg, task["start"], task["end"], daily_bars=True)
    monthly = {}
    prev = cfg.costs.initial_cash
    for p in result["curve"]:
        key = p["date"][:7]
        monthly[key] = (1 + monthly.get(key, 0)) * p["equity"] / prev - 1
        prev = p["equity"]
    midpoint = len(result["curve"]) // 2
    middle = result["curve"][midpoint - 1]["equity"]
    return dict(
        task=task,
        metrics=result["metrics"],
        months=monthly,
        halves=[middle / cfg.costs.initial_cash - 1, result["curve"][-1]["equity"] / middle - 1],
        half_boundary=result["curve"][midpoint]["date"],
        contributions=result["contributions"],
        curve=[
            {k: p[k] for k in ("date", "equity", "cash", "drawdown_pct")} for p in result["curve"]
        ],
        max_target_weight=max(
            a["target_weight"] for p in result["curve"] for a in p["assets"].values()
        ),
        forecast_failures=sum(
            f.get("status") == "optimizer_failed_cash"
            for p in result["curve"]
            for a in p["assets"].values()
            if (f := a.get("forecast"))
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--specialists", action="store_true")
    args = parser.parse_args()
    repo = Repository()
    ds = repo.get("datasets", args.dataset)
    assert ds["timeframe"] == "1Day"
    frame = repo.load_dataset(ds["id"])
    days = sorted(frame.day.unique())
    warmup = 127 if args.specialists else 63
    start = days[warmup]
    import pandas as pd

    end = str((pd.Timestamp(days[-1]) + pd.Timedelta(days=1)).date())
    tasks = []
    for method in METHODS + (["adaptive_specialist"] if args.specialists else []):
        for multiplier in (1, 2):
            cfg = PositionConfig(
                model=method,
                lookback=20,
                horizon=5,
                rebalance_days=5,
                tranche_weight=0.1,
                entry_band=0.005,
            )
            costs = cfg.costs.model_dump()
            for k in (
                "spread_bps",
                "slippage_bps",
                "commission_per_share",
                "minimum_commission",
                "sell_fee_bps",
            ):
                costs[k] *= multiplier
            tasks.append(
                dict(
                    dataset=ds["id"],
                    method=method,
                    cost_multiplier=multiplier,
                    start=start,
                    end=end,
                    config={**cfg.model_dump(), "costs": costs},
                )
            )
    for task in list(tasks):
        if task["method"] in ("trend", "equal_weight"):
            continue
        import copy

        shared = copy.deepcopy(task)
        shared["config"]["portfolio_policy"] = "cost_aware"
        shared["config"]["allocation"]["max_daily_turnover"] = 0.2
        shared["config"]["allocation"]["rebalance_band"] = 0.02
        tasks.append(shared)
    args.output.mkdir(parents=True, exist_ok=True)
    protocol = Path("docs/research-results/2026-09-18-principled-strategies-protocol.md")
    manifest = dict(
        dataset=ds,
        protocol_sha256=hashlib.sha256(protocol.read_bytes()).hexdigest(),
        warmup_days=warmup,
        evaluation_days=len(days) - warmup,
        tasks=tasks,
    )
    (args.output / "protocol.md").write_bytes(protocol.read_bytes())
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    rows = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(run, t) for t in tasks]):
            row = future.result()
            rows.append(row)
            (args.output / "results.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2)
            )
            m = row["metrics"]
            print(
                row["task"]["method"],
                row["task"]["config"]["portfolio_policy"],
                row["task"]["cost_multiplier"],
                round(m["return_pct"], 3),
                round(m["max_drawdown_pct"], 3),
                flush=True,
            )


if __name__ == "__main__":
    main()
