"""Conservative all-or-none pair research ledger, no live brokerage access."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from quant_workbench.market_data import schedule
from study_dual_class import PAIRS, ROOT


def trade(frame, decisions, a, b, start, end, mult):
    g = frame[frame.symbol.isin([a, b])]
    bars = {d: p.set_index("symbol") for d, p in g.groupby("day")}
    days = sorted(d for d in bars if start <= d < end)
    sch = schedule(str(frame.day.min()), end)
    mins = dict(
        zip(
            sch.index.strftime("%Y-%m-%d"),
            (sch.close - sch.open).dt.total_seconds() / 60,
            strict=True,
        )
    )
    cash = peak = 20000.0
    q = {a: 0, b: 0}
    flow = {a: 0.0, b: 0.0}
    pending = None
    position = None
    halted = False
    previous = None
    curve = []
    entries = exits = delayed = 0
    fees = impact_cost = carry = 0.0
    for i, d in enumerate(days):
        op = {s: float(bars[d].loc[s, "open"]) for s in [a, b]}
        cl = {s: float(bars[d].loc[s, "close"]) for s in [a, b]}
        if previous:
            for s in q:
                c = (
                    max(0, -q[s])
                    * float(bars[previous].loc[s, "close"])
                    * 0.05
                    * mult
                    * (pd.Timestamp(d) - pd.Timestamp(previous)).days
                    / 365
                )
                cash -= c
                flow[s] -= c
                carry += c
            caps = {
                s: int(float(bars[previous].loc[s, "volume"]) / mins[previous] * 0.01) for s in q
            }
            if pending:
                eq = cash + sum(q[s] * op[s] for s in q)
                if pending["kind"] == "exit":
                    order = {s: -q[s] for s in q}
                else:
                    direction = pending["direction"]
                    order = {
                        a: direction * int(0.475 * eq / op[a]),
                        b: -direction * int(0.475 * eq / op[b]),
                    }
                    ratio = min([1.0] + [caps[s] / abs(n) for s, n in order.items() if n])
                    order = {s: int(np.sign(n)) * int(abs(n) * ratio) for s, n in order.items()}
                    values = [abs(order[s]) * op[s] for s in q]
                    if (
                        not all(values)
                        or abs(values[0] - values[1]) / max(np.mean(values), 1) > 0.02
                    ):
                        order = {a: 0, b: 0}
                executable = all(abs(order[s]) <= caps[s] for s in q) and all(order.values())
                if executable:
                    for s, n in order.items():
                        p = op[s] + (1 if n > 0 else -1) * op[s] * 0.0003 * mult
                        fee = max(1.0, abs(n) * 0.005) * mult + (
                            abs(n) * p * 0.00003 * mult if n < 0 else 0
                        )
                        change = -n * p - fee
                        cash += change
                        flow[s] += change
                        q[s] += n
                        fees += fee
                        impact_cost += abs(n) * op[s] * 0.0003 * mult
                    if pending["kind"] == "entry":
                        position = {**pending, "index": i}
                        entries += 1
                    else:
                        position = None
                        exits += 1
                    pending = None
                else:
                    delayed += 1
        eq = cash + sum(q[s] * cl[s] for s in q)
        peak = max(peak, eq)
        halted = halted or eq <= peak * 0.9
        j = decisions[(a, d)]
        spread = math.log(cl[a] / cl[b])
        if position:
            if (
                halted
                or position["direction"] * (spread - position["mean"]) >= 0
                or abs(spread - position["mean"]) >= 4 * position["sigma"]
                or i - position["index"] >= 60
                or j["candidate_status"] != "通过"
            ):
                pending = {"kind": "exit"}
        elif not halted and j.get("entry_signal"):
            sigma = j["displacement"] / abs(j["z"])
            pending = dict(
                kind="entry",
                direction=-1 if j["z"] > 0 else 1,
                mean=spread - j["z"] * sigma,
                sigma=sigma,
            )
        else:
            pending = None
        curve.append(dict(date=d, equity=eq, gross=sum(abs(q[s]) * cl[s] for s in q) / eq))
        previous = d
    assert np.isclose(sum(flow[s] + q[s] * cl[s] for s in q), eq - 20000)
    return dict(
        pair=[a, b],
        return_pct=(eq / 20000 - 1) * 100,
        entries=entries,
        exits=exits,
        delayed_orders=delayed,
        fees=fees,
        impact_cost=impact_cost,
        carry_reserve=carry,
        halted=halted,
        open_position=position is not None,
        curve=curve,
    )


def main():
    f = pd.read_parquet(ROOT / "daily.parquet")
    audit = json.loads(Path("docs/research-results/2026-09-21-dual-class.json").read_text())
    ds = {(r["pair"][0], j["date"]): j for r in audit["results"] for j in r["decisions"]}
    results = []
    for start, end in [
        ("2024-09-01", "2025-09-01"),
        ("2025-09-01", "2026-09-01"),
        ("2024-09-01", "2026-09-01"),
    ]:
        for mult in (1, 2):
            rows = [trade(f, ds, a, b, start, end, mult) for a, b, _ in PAIRS]
            values = np.sum([[p["equity"] for p in r["curve"]] for r in rows], axis=0)
            peak = np.maximum.accumulate(np.r_[100000, values])[1:]
            row = dict(
                start=start,
                end_exclusive=end,
                cost_multiplier=mult,
                return_pct=float((values[-1] / 100000 - 1) * 100),
                max_drawdown_pct=float(max(1 - values / peak) * 100),
                pairs=rows,
            )
            results.append(row)
            print(
                start,
                end,
                mult,
                round(row["return_pct"], 3),
                [(r["pair"][0], round(r["return_pct"], 2), r["entries"]) for r in rows],
                flush=True,
            )
    Path("docs/research-results/2026-09-21-dual-class-trades.json").write_text(
        json.dumps(results, indent=2)
    )


if __name__ == "__main__":
    main()
