"""Economic identity and causal spread-screen audit, not a live trading recommendation."""

import json
import time
from pathlib import Path

import evaluate_alternate_universe as downloader
import httpx
import numpy as np

PAIRS = [
    ("GOOG", "GOOGL", 1652044),
    ("FOX", "FOXA", 1754301),
    ("NWS", "NWSA", 1564708),
    ("UA", "UAA", 1336917),
    ("HEI", "HEI.A", 46619),
]
ROOT = Path("artifacts/research/dual-class")
REPORT = Path("docs/research-results/2026-09-21-dual-class.json")


def screen(history, day, a, b):
    wide = history.pivot(index="day", columns="symbol", values="close").sort_index()
    past = wide.loc[wide.index < day, [a, b]].dropna().tail(126)
    if len(past) < 126 or day not in wide.index:
        return dict(candidate_status="证据不足", reason="需要126个完整历史日及当前收盘")
    y = np.log(past[a].to_numpy() / past[b].to_numpy())
    x = np.column_stack([np.ones(125), y[:-1]])
    change = np.diff(y)
    coef = np.linalg.lstsq(x, change, rcond=None)[0]
    error = change - x @ coef
    cov = float(error @ error / 123) * np.linalg.pinv(x.T @ x)
    beta = float(coef[1])
    se = float(np.sqrt(max(0, cov[1, 1])))
    t = beta / se if se > 1e-12 else None
    half = float(-np.log(2) / np.log(1 + beta)) if -1 < beta < 0 else None
    sigma = float(y.std(ddof=1))
    mean = float(y.mean())
    now = float(np.log(wide.loc[day, a] / wide.loc[day, b]))
    z = (now - mean) / sigma if sigma > 1e-8 else None
    drift = float(abs(y[:63].mean() - y[63:].mean()) / sigma) if sigma > 1e-8 else None
    liquid = []
    for symbol in [a, b]:
        g = history[(history.symbol == symbol) & (history.day < day)].tail(20)
        liquid.append(float((g.close * g.volume).median()))
    stationary = half is not None and 2 <= half <= 63 and t is not None and t < -2 and drift <= 1
    liquid_pass = all(v >= 1e7 for v in liquid)
    current = wide.loc[day]
    commission = sum(2 * max(1.0, 9500 / float(current[s]) * 0.005) / 9500 for s in (a, b))
    required_cost = 0.0012 + 0.00006 + commission + 0.05 * (half or 63) / 252
    displacement = abs(now - mean)
    candidate = bool(
        stationary
        and liquid_pass
        and z is not None
        and 2 <= abs(z) <= 4
        and displacement >= 2 * required_cost
    )
    return dict(
        status="证据不足",
        validation="缺少独立交易验证、借券与历史股权条款核验",
        candidate_status="通过" if stationary and liquid_pass else "未通过",
        entry_signal=candidate,
        beta=beta,
        t_stat=t,
        half_life=half,
        z=z,
        mean_shift_sigma=drift,
        median_dollar_volume=liquid,
        mean_reversion_screen=bool(stationary),
        liquidity_screen=bool(liquid_pass),
        displacement=displacement,
        estimated_cost=required_cost,
        window_start=str(past.index[0]),
        window_end=str(past.index[-1]),
    )


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    identities = []
    with httpx.Client(
        timeout=30, headers={"User-Agent": "QuantWorkbench academic research client"}
    ) as client:
        for a, b, cik in PAIRS:
            dest = ROOT / f"issuer-{cik}.json"
            if not dest.exists():
                r = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
                if r.status_code != 200:
                    raise ValueError(f"CIK {cik} HTTP {r.status_code}")
                dest.write_text(r.text)
                time.sleep(0.25)
            issuer = json.loads(dest.read_text())
            normalized = {s.replace("-", "."): s for s in issuer["tickers"]}
            if a not in normalized or b not in normalized:
                raise ValueError(f"Issuer mismatch {a} {b}: {issuer['tickers']}")
            identities.append(
                dict(a=a, b=b, cik=cik, name=issuer["name"], tickers=issuer["tickers"])
            )
    print("All five issuer identities verified", flush=True)
    downloader.SYMBOLS = sorted([s for a, b, _ in PAIRS for s in (a, b)])
    downloader.ROOT = ROOT
    frame = downloader.download("2024-03-01", "2026-09-01")
    results = []
    for start, end in [("2024-09-01", "2025-09-01"), ("2025-09-01", "2026-09-01")]:
        days = sorted(frame.loc[(frame.day >= start) & (frame.day < end), "day"].unique())
        for a, b, _ in PAIRS:
            sub = frame[frame.symbol.isin([a, b])].copy()
            decisions = [dict(date=d, **screen(sub, d, a, b)) for d in days]
            row = dict(
                start=start,
                end_exclusive=end,
                pair=[a, b],
                days=len(days),
                eligible_days=sum(j["candidate_status"] == "通过" for j in decisions),
                signals=sum(j.get("entry_signal", False) for j in decisions),
                decisions=decisions,
            )
            results.append(row)
            print(start, a, b, row["eligible_days"], row["signals"], flush=True)
            REPORT.write_text(
                json.dumps(
                    dict(status="running", identities=identities, results=results),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    REPORT.write_text(
        json.dumps(
            dict(status="completed", identities=identities, results=results),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
