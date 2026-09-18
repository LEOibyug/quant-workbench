"""Fixed-candidate, cost-aware walk-forward research on already-exposed historical data."""

import argparse
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
from quant_workbench.engine import ENGINE_VERSION, simulate
from quant_workbench.models import StrategyConfig
from quant_workbench.repository import Repository

FRAME = None


def initialize(path, expected_sha):
    global FRAME
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected_sha:
        raise ValueError("Dataset snapshot checksum mismatch")
    FRAME = pd.read_parquet(path)


def candidates(include_session=False, include_staged=False):
    base = StrategyConfig(
        initial_cash=100_000, max_hold_minutes=15, cooldown_minutes=10,
        max_daily_entries=4, risk_per_trade_bps=25, stop_atr=2, take_atr=4,
        rule_cost_multiplier=1.5, stat_horizon=15,
    ).model_dump()
    result = {}
    for window in (60, 120):
        for confidence in (0.0, 0.5):
            result[f"ou-w{window}-c{confidence}"] = dict(
                base, strategy="ou_reversion", stat_window=window, stat_confidence=confidence,
            )
    for noise in (0.001, 0.01):
        for confidence in (0.0, 0.5):
            result[f"kalman-q{noise}-c{confidence}"] = dict(
                base, strategy="kalman_trend", stat_process_noise=noise,
                stat_confidence=confidence,
            )
    for gate in ("off", "drift"):
        result[f"vwap-{gate}"] = dict(
            base, strategy="vwap_reversion", reversion_bps=70, stop_loss_bps=150,
            regime_gate=gate, regime_window_days=15, regime_min_drift_bps=50,
        )
    if include_session:
        for confidence in (0.0, 0.25, 0.5):
            result[f"bayesian-session-c{confidence}"] = dict(
                base, strategy="bayesian_session", stat_confidence=confidence,
                max_daily_entries=1,
            )
    if include_staged:
        for lots in (2, 3):
            result[f"ou-staged-{lots}"] = dict(
                base, strategy="ou_scaling", stat_window=120, stat_confidence=0.5,
                max_scaling_lots=lots, max_daily_entries=lots,
            )
        result["scaled-reversion-corrected"] = dict(
            base, strategy="scaled_reversion", reversion_bps=60, reversion_atr=1,
            stop_atr=3, max_scaling_lots=3, max_daily_entries=3,
            max_hold_minutes=120, cooldown_minutes=5,
        )
    return result


def evaluate(task):
    name, config, start, end, multiplier = task
    stressed = dict(config)
    for field in ("spread_bps", "slippage_bps", "commission_per_share",
                  "minimum_commission", "sell_fee_bps"):
        stressed[field] *= multiplier
    result = simulate(FRAME, StrategyConfig(**stressed), start, end)
    trades = pd.DataFrame(result["trades"])
    counts = {}
    if not trades.empty:
        sales = trades[(trades.side == "sell") & (trades.position_after == 0)]
        counts = sales.groupby(pd.to_datetime(sales.timestamp).dt.strftime("%Y-%m-%d")).size()
        counts = {key: int(value) for key, value in counts.items()}
    return dict(
        name=name, start=start, end=end, cost_multiplier=multiplier,
        metrics=result["metrics"], daily_returns=result["daily_returns"],
        daily_roundtrips=counts, contributions=result["contributions"],
    )


def compounded(values):
    return float((np.prod(1 + np.asarray(values) / 100) - 1) * 100)


def drawdown(values):
    equity = np.r_[1.0, np.cumprod(1 + np.asarray(values) / 100)]
    return float((1 - equity / np.maximum.accumulate(equity)).max() * 100)


def select(history, month):
    ranks = []
    for name, result in history.items():
        rows = [r for r in result["daily_returns"] if r["date"] < month][-20:]
        values = [r["return_pct"] for r in rows]
        count = sum(result["daily_roundtrips"].get(r["date"], 0) for r in rows)
        if len(rows) < 15 or count < 10:
            continue
        if min(compounded(values[:len(values)//2]), compounded(values[len(values)//2:])) <= 0:
            continue
        score = compounded(values) - 0.5 * drawdown(values)
        if score > 0:
            ranks.append((score, name))
    return max(ranks)[1] if ranks else "cash"


def bootstrap(values, repetitions=2000):
    rng = np.random.default_rng(20260918)
    values = np.asarray(values)
    outcomes = []
    for _ in range(repetitions):
        starts = rng.integers(0, len(values), size=(len(values) + 4) // 5)
        indices = np.concatenate([(s + np.arange(5)) % len(values) for s in starts])[:len(values)]
        outcomes.append(compounded(values[indices]))
    return [float(x) for x in np.percentile(outcomes, [2.5, 97.5])]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--include-session", action="store_true")
    parser.add_argument("--include-staged", action="store_true")
    parser.add_argument("--reuse", type=Path, help="Reuse candidates from the first fixed study")
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("workers must be 1–16")
    repo = Repository()
    dataset = repo.get("datasets", args.dataset)
    start, end = "2026-03-02", "2026-07-01"
    months = ["2026-04-01", "2026-05-01", "2026-06-01"]
    grid = candidates(args.include_session, args.include_staged)
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = dict(
        dataset=dataset, engine_version=ENGINE_VERSION, start=start, end=end,
        months=months, candidates=grid, fresh_holdout=False,
        selection="Prior 20 sessions only; >=15 days, >=10 roundtrips, both halves positive; "
        "maximize net return minus 0.5 * daily drawdown if positive, otherwise cash.",
        evaluation="Monthly restart at equal initial capital; config fixed before month; "
        "2x cost stress uses same selected config; all dates previously exposed.",
    )
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2, ensure_ascii=False))
    path = str(repo.path("datasets", args.dataset, ".parquet"))
    history = {}
    if args.reuse:
        original = json.loads((args.reuse / "protocol.json").read_text())
        if (original["dataset"]["sha256"] != dataset["sha256"]
                or original["engine_version"] != ENGINE_VERSION):
            raise ValueError("Cannot reuse results from another dataset or engine")
        for name, result in json.loads((args.reuse / "candidate-results.json").read_text()).items():
            if name in grid and original["candidates"][name] == grid[name]:
                history[name] = result
    with ProcessPoolExecutor(
        max_workers=args.workers, initializer=initialize, initargs=(path, dataset["sha256"]),
    ) as pool:
        tasks = [(name, cfg, start, end, 1) for name, cfg in grid.items() if name not in history]
        for result in pool.map(evaluate, tasks):
            history[result["name"]] = result
            print(f"{result['name']}: {result['metrics']['return_pct']:+.3f}% "
                  f"({result['metrics']['roundtrips']} roundtrips)", flush=True)
            (args.output / "candidate-results.json").write_text(json.dumps(history, indent=2))
        selected, stressed = [], []
        selections = []
        for i, month in enumerate(months):
            boundary = months[i + 1] if i + 1 < len(months) else end
            chosen = select(history, month)
            selections.append(dict(month=month, selected=chosen))
            if chosen == "cash":
                days = [r["date"] for r in next(iter(history.values()))["daily_returns"]
                        if month <= r["date"] < boundary]
                result = dict(name="cash", daily_returns=[dict(date=d, return_pct=0) for d in days],
                              metrics=dict(return_pct=0, roundtrips=0), contributions=[])
                stress = result
            else:
                result, stress = list(pool.map(evaluate, [
                    (chosen, grid[chosen], month, boundary, 1),
                    (chosen, grid[chosen], month, boundary, 2),
                ]))
            selected.append(result)
            stressed.append(stress)
            print(f"{month}: select {chosen} → {result['metrics']['return_pct']:+.3f}% "
                  f"(2x costs {stress['metrics']['return_pct']:+.3f}%)", flush=True)
    values = [r["return_pct"] for month in selected for r in month["daily_returns"]]
    stress_values = [r["return_pct"] for month in stressed for r in month["daily_returns"]]
    report = dict(
        protocol=protocol, selections=selections, selected_months=selected,
        stress_months=stressed, candidate_results=history,
        walk_forward_return_pct=compounded(values), daily_max_drawdown_pct=drawdown(values),
        cost_stress_return_pct=compounded(stress_values),
        bootstrap_95_pct=bootstrap(values), fresh_holdout=False,
        deployment="research_only; no live orders; new untouched data required",
    )
    (args.output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in (
        "walk_forward_return_pct", "daily_max_drawdown_pct", "cost_stress_return_pct",
        "bootstrap_95_pct", "fresh_holdout",
    )}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
