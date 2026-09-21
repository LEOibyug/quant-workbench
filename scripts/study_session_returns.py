"""Return decomposition and idealized fixed-dollar auction feasibility screen."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("docs/research-results")


def decompose(frame):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    opening = frame.pivot(index="day", columns="symbol", values="open").reindex(
        index=p.index, columns=p.columns
    )
    closes, opens = p.to_numpy(), opening.to_numpy()
    intraday = np.log(closes / opens).sum(axis=0)
    overnight = np.log(opens[1:] / closes[:-1]).sum(axis=0)
    total = np.log(closes[-1] / opens[0])
    np.testing.assert_allclose(intraday + overnight, total, atol=1e-12)
    return (
        p.index,
        p.columns,
        opens,
        closes,
        dict(
            zip(
                p.columns,
                [
                    dict(intraday_log=float(a), overnight_log=float(b), total_log=float(c))
                    for a, b, c in zip(intraday, overnight, total, strict=True)
                ],
                strict=True,
            )
        ),
    )


def simulate(opens, closes, mode, costs, multiplier):
    equity = float(costs["initial_cash"])
    fee_total = impact_total = 0.0
    if mode == "intraday":
        pairs = list(zip(opens, closes, strict=True))
    elif mode == "overnight":
        pairs = list(zip(closes[:-1], opens[1:], strict=True))
    elif mode == "continuous":
        pairs = [(opens[0], closes[-1])]
    else:
        raise ValueError(mode)
    curve = []
    for entry, exit_price in pairs:
        impact = (costs["spread_bps"] / 2 + costs["slippage_bps"]) * multiplier / 10000
        entry_fill = entry * (1 + impact)
        exit_fill = exit_price * (1 - impact)
        shares = 0.95 * equity / len(entry) / entry_fill
        commission = np.maximum(
            costs["minimum_commission"] * multiplier,
            shares * costs["commission_per_share"] * multiplier,
        )
        sell_fee = shares * exit_fill * costs["sell_fee_bps"] * multiplier / 10000
        cash = equity - float(shares @ entry_fill) - float(commission.sum())
        if cash < 0:
            raise ValueError("Commission exceeds reserve")
        equity = cash + float(shares @ exit_fill) - float(commission.sum() + sell_fee.sum())
        fee_total += float(2 * commission.sum() + sell_fee.sum())
        impact_total += float(shares @ (entry * impact + exit_price * impact))
        curve.append(equity)
    return dict(
        return_pct=(equity / costs["initial_cash"] - 1) * 100,
        end_equity=equity,
        cycles=len(pairs),
        orders=2 * len(pairs) * opens.shape[1],
        fees=fee_total,
        impact=impact_total,
        cycle_end_equity=curve,
    )


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    costs = next(
        r["config"]["costs"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    results = []
    decomposition = {}
    for pool, meta in manifest.items():
        f = pd.read_parquet(meta["path"])
        f = f[(f.day >= "2025-09-01") & (f.day < "2026-09-01")]
        days, symbols, opens, closes, parts = decompose(f)
        decomposition[pool] = dict(symbols=list(symbols), days=list(days), parts=parts)
        for mode in ("intraday", "overnight", "continuous"):
            for mult in (0, 1, 2):
                r = simulate(opens, closes, mode, costs, mult)
                r.update(pool=pool, mode=mode, cost_multiplier=mult)
                results.append(r)
                print(pool, mode, mult, r["return_pct"], flush=True)
    (ROOT / "2026-09-21-session-returns.json").write_text(
        json.dumps(
            dict(status="completed", costs=costs, results=results, decomposition=decomposition),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
