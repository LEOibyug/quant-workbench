"""Post-halt whole-share liquidation accounting diagnostic, not an execution engine."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from spinoff_marks import ChildMarks

ROOT = Path("docs/research-results")


def assess(row, marks):
    curve = row["curve"]
    initial = row["config"]["costs"]["initial_cash"]
    first = next((i for i, p in enumerate(curve) if p["halted"]), None)
    base = dict(
        start=row["start"],
        end_exclusive=row["end_exclusive"],
        method=row["method"],
        multiplier=row["multiplier"],
        actual_return_pct=row["metrics"]["return_pct"],
    )
    if first is None or first + 1 == len(curve):
        return dict(**base, status="no_executable_post_halt_session")
    assert all(p["halted"] for p in curve[first:])
    for previous, current in zip(curve[first:-1], curve[first + 1 :], strict=True):
        assert all(current["positions"][s] <= q for s, q in previous["positions"].items())
    last_assets = curve[first]["distributed_assets"]["assets"]
    quantities = {k: v["shares"] for k, v in last_assets.items() if v["shares"] > 0}
    if not quantities:
        return dict(
            **base,
            status="no_whole_side_assets",
            counterfactual_return_pct=base["actual_return_pct"],
        )
    for p in curve[first:]:
        assert {
            k: v["shares"] for k, v in p["distributed_assets"]["assets"].items() if v["shares"] > 0
        } == quantities
    assert all(e["day"] <= curve[first]["date"] for e in row["distribution_audit"])
    day = curve[first + 1]["date"]
    costs = row["config"]["costs"]
    orders = []
    for key, quantity in quantities.items():
        symbol = last_assets[key]["symbol"]
        raw = marks.at(day, [symbol], "open")[symbol]
        price = raw * (1 - (costs["spread_bps"] / 2 + costs["slippage_bps"]) / 10000)
        fee = max(costs["minimum_commission"], quantity * costs["commission_per_share"])
        fee += quantity * price * costs["sell_fee_bps"] / 10000
        orders.append(
            dict(
                symbol=symbol,
                quantity=quantity,
                raw_open=raw,
                price=price,
                fee=fee,
                net_cash=quantity * price - fee,
            )
        )
    cash = sum(o["net_cash"] for o in orders)
    result = []
    for i, p in enumerate(curve):
        removed = (
            sum(quantities[k] * p["distributed_assets"]["assets"][k]["mark"] for k in quantities)
            if i > first
            else 0
        )
        equity = p["equity"] - removed + (cash if i > first else 0)
        result.append(dict(date=p["date"], equity=equity))
    wealth = np.r_[initial, [p["equity"] for p in result]]
    dd = 100 * np.max(1 - wealth / np.maximum.accumulate(wealth))
    end_side = curve[-1]["distributed_assets"]["assets"]
    fractional = sum(v["fractional_receivable"] * v["mark"] for v in end_side.values())
    return dict(
        **base,
        status="accounting_counterfactual",
        halt_date=curve[first]["date"],
        exit_date=day,
        orders=orders,
        counterfactual_return_pct=(wealth[-1] / initial - 1) * 100,
        counterfactual_max_drawdown_pct=float(dd),
        terminal_hold_minus_exit_dollars=curve[-1]["equity"] - wealth[-1],
        fractional_receivable_retained=fractional,
        curve=result,
    )


def main():
    source = ROOT / "2026-09-21-distribution-expanded.full.json.gz"
    rows = json.loads(gzip.decompress(source.read_bytes()))["results"]
    marks = ChildMarks(str(ROOT / "2026-09-21-spinoff-history.json"))
    out = [assess(r, marks) for r in rows if r["variant"] == "with_distribution"]
    (ROOT / "2026-09-21-side-asset-exit.json").write_text(
        json.dumps(
            dict(
                status="completed",
                validated=False,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                results=out,
            ),
            indent=2,
        )
        + "\n"
    )
    for r in out:
        print({k: v for k, v in r.items() if k not in ("curve", "orders")})


if __name__ == "__main__":
    main()
