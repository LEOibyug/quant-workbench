"""Daily valuation reconciliation of one frozen hypothetical distribution holding."""

import json
from pathlib import Path

import pandas as pd
from spinoff_marks import ChildMarks
from spinoff_transition import DistributionState


def main():
    frame = pd.read_parquet("artifacts/research/alternate-history/daily.parquet")
    marks = ChildMarks("docs/research-results/2026-09-21-spinoff-history.json")
    rows = []
    for parent, child, day, denominator in [
        ("GE", "GEHC", "2023-01-04", 3),
        ("GE", "GEV", "2024-04-02", 4),
        ("IBM", "KD", "2021-11-04", 5),
    ]:
        f = frame[frame.symbol == parent].sort_values("day").set_index("day")
        i = f.index.get_loc(day)
        basis = float(f.close.iloc[i - 1])
        quantity = 101
        # Standalone valuation experiment, not the real strategy's positions or buy orders.
        book = DistributionState()
        initial = quantity * basis
        result = book.apply_before_risk(
            dict(id=child, child=child, numerator=1, denominator=denominator, verified=True),
            quantity,
            basis,
            float(f.loc[day, "open"]),
            marks.at(day, [child], "open")[child],
        )
        new_basis = result["parent_basis"]
        audited = 0
        # Stop before another known parent distribution: each path tests one event only.
        end = "2024-04-02" if child == "GEHC" else "2025-09-01"
        for date, p in f[(f.index >= day) & (f.index < end)].iterrows():
            child_value = book.mark(marks.at(date, [child], "close"))
            equity = quantity * float(p.close) + child_value["market_value"]
            pnl = quantity * (float(p.close) - new_basis) + child_value["unrealized_pnl"]
            assert abs(equity - initial - pnl) < 1e-8
            audited += 1
        rows.append(
            dict(
                parent=parent,
                child=child,
                first_session=day,
                end_exclusive=end,
                assumed_parent_shares=quantity,
                sessions_reconciled=audited,
                initial_parent_cost=initial,
                parent_basis_after=new_basis,
                child_cost=sum(book.child_cost.values()),
                cash_credited=0,
                note="Hypothetical valuation only; unsettled fractional claim; not strategy return",
            )
        )
    # Pre-listing and non-session quotes must not silently become stale values.
    for day in ["2024-04-01", "2024-04-06"]:
        try:
            marks.at(day, ["GEV"], "close")
        except ValueError:
            pass
        else:
            raise AssertionError("Expected unavailable quote rejection")
    Path("docs/research-results/2026-09-21-distribution-path-audit.json").write_text(
        json.dumps(rows, indent=2)
    )
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
