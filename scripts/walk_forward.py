"""Walk-forward evaluation protocol for regime-gated configurations.

Motivated by the 2026-09-18 search log: a validation-period winner failed the
one-shot final test because a single validation month carries one market style.
This script estimates the SELECTION PROCESS instead of a single config: for each
evaluation month it re-runs the full selection on strictly earlier data only,
then applies the selected configuration to that month.

Honesty constraints encoded here:
- the candidate list and selection rule are fixed up front;
- selection sees only data strictly before the evaluation month;
- the base strategy (vwap_reversion 70/150) was pre-registered in the prior
  search and is not re-tuned here;
- months previously exposed to research (the final test month) must be flagged
  by the caller, since mechanism design itself has seen them.

Usage:
  uv run --extra neural python scripts/walk_forward.py --dataset <id> \
      --months 2026-04-01 2026-05-01 2026-06-01 --end 2026-07-01
"""

import argparse
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

os.environ.setdefault("QUANT_TORCH_DEVICE", "cpu")

BASE = dict(
    strategy="vwap_reversion",
    fast=8,
    slow=21,
    reversion_bps=70.0,
    stop_loss_bps=150.0,
    initial_cash=100000.0,
    spread_bps=2.0,
    slippage_bps=2.0,
    commission_per_share=0.0,
    minimum_commission=0.0,
    sell_fee_bps=0.3,
    participation=0.01,
    flatten_minutes=5,
    opening_minutes=15,
)


def candidates():
    out = [dict(BASE, regime_gate="off")]
    # 分批波动收割候选（机制对照：诚实协议是否会选择它）。
    for band, satr, lots in ((60.0, 3.0, 3), (40.0, 2.0, 3), (50.0, 3.0, 2)):
        out.append(
            dict(
                BASE,
                strategy="scaled_reversion",
                reversion_bps=band,
                reversion_atr=1.0,
                stop_atr=satr,
                max_scaling_lots=lots,
                max_daily_entries=lots,
                max_hold_minutes=120,
                take_atr=3.0,
                cooldown_minutes=5,
                regime_gate="off",
            )
        )
    for gate, window, drift, eff in itertools.product(
        ("drift", "efficiency", "drift_and_efficiency", "drift_or_efficiency"),
        (5, 10, 15),
        (0.0, 50.0, 100.0),
        (0.3, 0.45, 0.6),
    ):
        if gate in ("drift", "drift_or_efficiency") and eff != 0.45:
            continue  # 不依赖效率参数的门只保留一组，避免候选重复
        if gate == "efficiency" and (drift != 50.0):
            continue
        out.append(
            dict(
                BASE,
                regime_gate=gate,
                regime_window_days=window,
                regime_min_drift_bps=drift,
                regime_max_efficiency=eff,
            )
        )
    return out


def _dataset_frame(path):
    import pandas as pd

    return pd.read_parquet(path)


def _run(args):
    from quant_workbench.engine import simulate
    from quant_workbench.models import StrategyConfig

    cfg, frame, start, end = args
    metrics = simulate(frame, StrategyConfig(**cfg), start, end)["metrics"]
    return round(metrics["return_pct"], 4), metrics.get("roundtrips", 0)


def _eval_many(cfgs, frame, start, end, workers):
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(
            pool.map(
                _run,
                [(cfg, frame, start, end) for cfg in cfgs],
                chunksize=1,
            )
        )
    return [
        dict(cfg=cfg, net=net, roundtrips=rt)
        for cfg, (net, rt) in zip(cfgs, rows, strict=True)
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="dataset id or parquet path")
    parser.add_argument("--start", default="2026-03-02")
    parser.add_argument("--months", nargs="+", required=True, help="evaluation month starts")
    parser.add_argument("--end", required=True, help="exclusive end of the last month")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    path = args.dataset
    if not path.endswith(".parquet"):
        root = args.data_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
        )
        path = os.path.join(root, "datasets", f"{args.dataset}.parquet")
    frame = _dataset_frame(path)

    # 预注册候选；每月先用严格更早的数据全量重选，再评估当月。
    grid = candidates()
    report = dict(
        protocol="expanding-window walk-forward; selection on strictly earlier data",
        candidates=len(grid),
        months=[],
    )
    equity = 1.0
    for month_start in args.months:
        month_end = (
            args.months[args.months.index(month_start) + 1]
            if args.months.index(month_start) + 1 < len(args.months)
            else args.end
        )
        selection = _eval_many(grid, frame, args.start, month_start, args.workers)
        selection.sort(key=lambda r: (r["net"], -r["roundtrips"]), reverse=True)
        chosen = selection[0]
        evaluated = _eval_many([chosen["cfg"]], frame, month_start, month_end, args.workers)[0]
        equity *= 1 + evaluated["net"] / 100
        report["months"].append(
            dict(
                month=month_start,
                selected_gate=chosen["cfg"]["regime_gate"],
                window=chosen["cfg"].get("regime_window_days"),
                drift=chosen["cfg"].get("regime_min_drift_bps"),
                efficiency=chosen["cfg"].get("regime_max_efficiency"),
                selection_net=chosen["net"],
                evaluated_net=evaluated["net"],
                evaluated_roundtrips=evaluated["roundtrips"],
            )
        )
        print(
            f"{month_start}: gate={chosen['cfg']['regime_gate']}"
            f"(w={chosen['cfg'].get('regime_window_days')}) "
            f"selection {chosen['net']:+.3f}% -> month {evaluated['net']:+.3f}% "
            f"({evaluated['roundtrips']} rt)",
            flush=True,
        )
    ungated = 1.0
    for month_start in args.months:
        month_end = (
            args.months[args.months.index(month_start) + 1]
            if args.months.index(month_start) + 1 < len(args.months)
            else args.end
        )
        row = _eval_many(
            [dict(BASE, regime_gate="off")], frame, month_start, month_end, args.workers
        )[0]
        ungated *= 1 + row["net"] / 100
    report["walk_forward_return_pct"] = round((equity - 1) * 100, 3)
    report["ungated_fixed_return_pct"] = round((ungated - 1) * 100, 3)
    print(
        f"\nwalk-forward total: {report['walk_forward_return_pct']:+.3f}%"
        f" | ungated fixed: {report['ungated_fixed_return_pct']:+.3f}%"
    )
    out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "artifacts"
    )
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "walk-forward-report.json"), "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print("report written to artifacts/walk-forward-report.json")


if __name__ == "__main__":
    sys.exit(main())
