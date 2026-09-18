"""Predeclared long-horizon comparisons with staged execution and 2x-cost stress."""

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from statistical_study import bootstrap, compounded

FRAME = None


def initialize(path, expected_sha):
    global FRAME
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected_sha:
        raise ValueError("Dataset snapshot checksum mismatch")
    FRAME = pd.read_parquet(path)


def run(task):
    name, config, multiplier = task
    config = dict(config)
    costs = dict(config["costs"])
    for field in ("spread_bps", "slippage_bps", "commission_per_share",
                  "minimum_commission", "sell_fee_bps"):
        costs[field] *= multiplier
    config["costs"] = costs
    result = simulate_positions(FRAME, PositionConfig(**config), "2026-04-01", "2026-07-01")
    return name, multiplier, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = Repository()
    dataset = repo.get("datasets", args.dataset)
    grid = {}
    for model in ("trend", "bayesian"):
        for lookback in (20, 40):
            for confidence in (0.0, 0.5):
                grid[f"{model}-w{lookback}-c{confidence}"] = PositionConfig(
                    model=model, lookback=lookback, confidence=confidence,
                ).model_dump()
    grid["equal_weight"] = PositionConfig(model="equal_weight").model_dump()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = dict(dataset=dataset, candidates=grid, fresh_holdout=False,
                    start="2026-04-01", end="2026-07-01", calibration_history="2026-03-02 onward",
                    candidate_selection="None: fixed model comparisons, all attempts retained",
                    overnight=True, staged=True, short_and_long_capital="independent accounts")
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    summary = {}
    with ProcessPoolExecutor(
        max_workers=3, initializer=initialize,
        initargs=(str(repo.path("datasets", args.dataset, ".parquet")), dataset["sha256"]),
    ) as pool:
        tasks = [(name, config, stress) for name, config in grid.items() for stress in (1, 2)]
        for name, stress, result in pool.map(run, tasks):
            (args.output / f"{name}-{stress}x.json").write_text(json.dumps(result, indent=2))
            daily = result["daily_returns"]
            summary.setdefault(name, {})[str(stress)] = dict(
                metrics=result["metrics"], contributions=result["contributions"],
                monthly={month: compounded([r["return_pct"] for r in daily
                                           if r["date"].startswith(month)])
                         for month in ("2026-04", "2026-05", "2026-06")},
                bootstrap_95_pct=bootstrap([r["return_pct"] for r in daily]),
                positions=result["positions"],
            )
            print(f"{name} {stress}x: {result['metrics']['return_pct']:+.3f}% / "
                  f"DD {result['metrics']['max_drawdown_pct']:.3f}% / "
                  f"{result['metrics']['trade_count']} fills", flush=True)
            (args.output / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
