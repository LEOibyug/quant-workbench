"""Research-only signed-share cash ledger; not connected to any broker."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from quant_workbench.market_data import schedule
from quant_workbench.repository import Repository
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")


def forecasts(frame, mode):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    log = np.log(p.to_numpy())
    r = np.diff(log, axis=0)
    out = {}
    for i in range(126, len(p)):
        cov = LedoitWolf().fit(r[i - 63 : i]).covariance_ + np.eye(p.shape[1]) * 1e-12
        inv = 1 / np.sqrt(np.diag(cov))
        signal = np.mean([np.sign(log[i] - log[i - k]) for k in (21, 63, 126)], axis=0)
        if mode == "long_only":
            signal = np.maximum(signal, 0)
        if mode == "risk_only":
            signal = np.ones_like(signal)
        w = np.clip(0.95 * inv / inv.sum() * signal, -0.2, 0.2)
        w *= min(1, 0.1 / max(np.sqrt(w @ cov @ w * 252), 1e-12))
        out[str(p.index[i])] = dict(zip(p.columns, w.tolist(), strict=True))
    return out


def simulate(frame, mode, multiplier=1, start="2025-09-01", end="2026-09-01", rebalance_days=5):
    frame = frame[frame.day < end].sort_values(["day", "symbol"])
    fc = forecasts(frame, mode)
    symbols = sorted(frame.symbol.unique())
    cash = peak = 100000.0
    shares = {s: 0 for s in symbols}
    target = shares.copy()
    flows = {s: 0.0 for s in symbols}
    data = {d: g.set_index("symbol") for d, g in frame.groupby("day")}
    days = sorted(d for d in data if start <= d < end)
    sessions = schedule(str(frame.day.min()), end)
    mins = dict(
        zip(
            sessions.index.strftime("%Y-%m-%d"),
            (sessions.close - sessions.open).dt.total_seconds() / 60,
            strict=True,
        )
    )
    halted = False
    previous = None
    curve = []
    trades = []
    fees = impact_total = carry_total = 0.0
    for i, day in enumerate(days):
        bars = data[day]
        opens = {s: float(bars.loc[s, "open"]) for s in symbols}
        closes = {s: float(bars.loc[s, "close"]) for s in symbols}
        if previous is not None:
            elapsed = (pd.Timestamp(day) - pd.Timestamp(previous)).days
            for s in symbols:
                charge = (
                    max(0, -shares[s])
                    * float(data[previous].loc[s, "close"])
                    * (0.03 + 0.02)
                    * multiplier
                    * elapsed
                    / 365
                )
                cash -= charge
                flows[s] -= charge
                carry_total += charge
            equity = cash + sum(shares[s] * opens[s] for s in symbols)
            halted = halted or equity <= peak * 0.9
            if halted:
                target = {s: 0 for s in symbols}
            # Split flips into a reduction and a new exposure; same per-stock daily cap.
            caps = {
                s: int(float(data[previous].loc[s, "volume"]) / mins[previous] * 0.01)
                for s in symbols
            }
            steps = {s: int(max(equity, 0) * 0.1 / opens[s]) for s in symbols}
            used = {s: 0 for s in symbols}
            for reducing in (True, False):
                for s in symbols:
                    current = shares[s]
                    desired = target[s]
                    if reducing:
                        if current == 0:
                            continue
                        endpoint = (
                            0
                            if current * desired <= 0
                            else np.sign(current) * min(abs(current), abs(desired))
                        )
                    else:
                        endpoint = desired
                    delta = int(endpoint - current)
                    if not delta:
                        continue
                    limit = caps[s] - used[s]
                    if not halted:
                        limit = min(limit, steps[s] - used[s])
                    quantity = min(abs(delta), max(0, limit))
                    if not reducing:
                        current_equity = cash + sum(shares[x] * opens[x] for x in symbols)
                        gross = sum(abs(shares[x]) * opens[x] for x in symbols)
                        quantity = min(
                            quantity, int(max(0, 0.95 * current_equity - gross) / opens[s])
                        )
                    if quantity <= 0:
                        continue
                    signed = int(np.sign(delta)) * quantity
                    impact = opens[s] * 0.0003 * multiplier
                    price = opens[s] + (1 if delta > 0 else -1) * impact
                    fee = max(1.0, quantity * 0.005) * multiplier
                    if signed < 0:
                        fee += quantity * price * 0.00003 * multiplier
                    flow = -signed * price - fee
                    cash += flow
                    flows[s] += flow
                    shares[s] += signed
                    used[s] += quantity
                    fees += fee
                    impact_total += quantity * impact
                    trades.append(dict(date=day, symbol=s, quantity=signed, price=price, fee=fee))
        equity = cash + sum(shares[s] * closes[s] for s in symbols)
        peak = max(peak, equity)
        halted = halted or equity <= 0.9 * peak
        if i % rebalance_days == 0:
            w = fc.get(day, {})
            target = {
                s: int(np.sign(w.get(s, 0)) * np.floor(abs(w.get(s, 0)) * equity / closes[s]))
                for s in symbols
            }
        if halted:
            target = {s: 0 for s in symbols}
        curve.append(
            dict(
                date=day,
                equity=equity,
                cash=cash,
                drawdown_pct=(1 - equity / peak) * 100,
                gross=sum(abs(shares[s]) * closes[s] for s in symbols) / equity,
                net=sum(shares[s] * closes[s] for s in symbols) / equity,
                halted=halted,
            )
        )
        previous = day
    values = np.array([100000] + [p["equity"] for p in curve])
    ret = values[1:] / values[:-1] - 1
    contributions = {s: flows[s] + shares[s] * closes[s] for s in symbols}
    assert np.isclose(sum(contributions.values()), equity - 100000, atol=1e-6)
    return dict(
        mode=mode,
        cost_multiplier=multiplier,
        return_pct=(equity / 100000 - 1) * 100,
        max_drawdown_pct=max(p["drawdown_pct"] for p in curve),
        sharpe=(
            float(ret.mean() / ret.std(ddof=1) * np.sqrt(252)) if ret.std(ddof=1) > 1e-12 else None
        ),
        average_gross_pct=float(np.mean([p["gross"] for p in curve]) * 100),
        average_net_pct=float(np.mean([p["net"] for p in curve]) * 100),
        fees=fees,
        impact_cost=impact_total,
        carry_reserve=carry_total,
        trades=len(trades),
        halted=halted,
        contributions=contributions,
        curve=curve,
    )


def main():
    meta = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    pools = {
        "original20": Repository().load_dataset(meta["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    dest = ROOT / "2026-09-21-symmetric-trend.json"
    for pool, frame in pools.items():
        for mode in ("signed", "long_only", "risk_only"):
            for mult in (1, 2):
                r = simulate(frame, mode, mult)
                r["pool"] = pool
                results.append(r)
                print(
                    pool,
                    mode,
                    mult,
                    round(r["return_pct"], 3),
                    round(r["max_drawdown_pct"], 3),
                    flush=True,
                )
                dest.write_text(json.dumps(dict(status="running", results=results), indent=2))
    dest.write_text(json.dumps(dict(status="completed", results=results), indent=2))


if __name__ == "__main__":
    main()
