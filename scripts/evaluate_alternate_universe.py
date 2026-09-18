"""Frozen second-universe comparison; local artifacts only, no web catalog writes."""

import hashlib
import json
import os
from pathlib import Path

import httpx
import pandas as pd
from quant_workbench.daily_data import normalize_daily
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.provider_windows import quarter_windows
from quant_workbench.providers import _get

SYMBOLS = sorted(
    "ADBE CRM CSCO IBM INTC QCOM TXN BAC GS MS UNH MRK ABBV PG KO PEP HD CAT GE CVX".split()
)
ROOT = Path("artifacts/research/alternate-universe-2025")
REPORT = Path("docs/research-results/2026-09-18-alternate-universe.json")


def download():
    ROOT.mkdir(parents=True, exist_ok=True)
    frames = []
    headers = {
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"],
    }
    with httpx.Client(timeout=45) as client:
        for start, end in quarter_windows("2025-02-28", "2026-09-01"):
            path = ROOT / f"{start}-{end}-raw.parquet"
            if path.exists():
                frame = pd.read_parquet(path)
            else:
                params = dict(
                    symbols=",".join(SYMBOLS),
                    timeframe="1Day",
                    start=str(start),
                    end=str(end),
                    adjustment="raw",
                    feed="sip",
                    limit=10000,
                )
                records = []
                seen = set()
                while True:
                    response = _get(
                        client,
                        "https://data.alpaca.markets/v2/stocks/bars",
                        headers=headers,
                        params=params,
                    )
                    if response.status_code != 200:
                        raise ValueError(f"Alpaca HTTP {response.status_code}")
                    data = response.json()
                    for symbol, bars in data.get("bars", {}).items():
                        if symbol not in SYMBOLS:
                            raise ValueError("Unexpected symbol")
                        for b in bars:
                            day = (
                                pd.Timestamp(b["t"])
                                .tz_convert("America/New_York")
                                .strftime("%Y-%m-%d")
                            )
                            if str(start) <= day < str(end):
                                records.append(
                                    dict(
                                        day=day,
                                        symbol=symbol,
                                        open=b["o"],
                                        high=b["h"],
                                        low=b["l"],
                                        close=b["c"],
                                        volume=b["v"],
                                    )
                                )
                    token = data.get("next_page_token")
                    if not token:
                        break
                    if token in seen:
                        raise ValueError("Repeated page token")
                    seen.add(token)
                    params["page_token"] = token
                frame = normalize_daily(pd.DataFrame(records))
                frame.to_parquet(path, index=False)
            frames.append(frame)
            print(f"{start}—{end}: {len(frame)} rows", flush=True)
    frame = normalize_daily(pd.concat(frames, ignore_index=True))
    expected = set(schedule("2025-02-28", "2026-09-01").index.strftime("%Y-%m-%d"))
    if set(frame.symbol) != set(SYMBOLS):
        raise ValueError("Incomplete universe")
    gaps = []
    for symbol, g in frame.groupby("symbol"):
        g = g.sort_values("day")
        if set(g.day) != expected:
            raise ValueError(f"{symbol}: incomplete sessions")
        ratio = g.open.to_numpy()[1:] / g.close.to_numpy()[:-1]
        for i in range(len(ratio)):
            if ratio[i] < 0.65 or ratio[i] > 1.5:
                gaps.append(dict(symbol=symbol, day=g.day.iloc[i + 1], ratio=float(ratio[i])))
    if gaps:
        raise ValueError(f"Unverified price jumps: {gaps}")
    frame.to_parquet(ROOT / "daily.parquet", index=False)
    return frame


def main():
    prior = json.loads(Path("docs/research-results/2026-09-18-pattern-policy-v2.json").read_text())
    if set(SYMBOLS) & set(prior["evaluation_dataset"]["symbols"]):
        raise ValueError("Universes overlap")
    original = next(
        x for x in prior["results"] if x["method"] == "fixed_ensemble" and x["cost_multiplier"] == 1
    )
    config = original["config"]
    frame = download()
    rows = []
    for method in ("fixed_ensemble", "equal_weight"):
        for multiplier in (1, 2):
            costs = dict(config["costs"])
            for key in (
                "spread_bps",
                "slippage_bps",
                "commission_per_share",
                "minimum_commission",
                "sell_fee_bps",
            ):
                costs[key] *= multiplier
            cfg = PositionConfig(**{**config, "model": method, "costs": costs})
            result = simulate_positions(frame, cfg, "2025-09-01", "2026-09-01", daily_bars=True)
            (ROOT / f"{method}-{multiplier}.json").write_text(
                json.dumps(result, ensure_ascii=False)
            )
            curve = pd.DataFrame(result["curve"])
            curve["month"] = curve.date.str[:7]
            monthly = []
            previous = cfg.costs.initial_cash
            for month, g in curve.groupby("month", sort=True):
                equity = float(g.equity.iloc[-1])
                monthly.append(dict(month=month, return_pct=(equity / previous - 1) * 100))
                previous = equity
            row = dict(
                method=method,
                cost_multiplier=multiplier,
                config=result["config"],
                metrics=result["metrics"],
                contributions=result["contributions"],
                monthly_returns=monthly,
                first_halt=next((x["date"] for x in result["curve"] if x["halted"]), None),
                curve=[
                    {k: x[k] for k in ("date", "equity", "cash", "drawdown_pct")}
                    for x in result["curve"]
                ],
            )
            rows.append(row)
            print(method, multiplier, result["metrics"], flush=True)
    trading = frame[frame.day >= "2025-09-01"].sort_values("day")
    gross = {
        s: (float(g.close.iloc[-1]) / float(g.open.iloc[0]) - 1) * 100
        for s, g in trading.groupby("symbol")
    }
    report = dict(
        symbols=SYMBOLS,
        start="2025-09-01",
        end_exclusive="2026-09-01",
        warmup_start="2025-02-28",
        rows=len(frame),
        sha256=hashlib.sha256((ROOT / "daily.parquet").read_bytes()).hexdigest(),
        provider="alpaca-sip-raw",
        original_config_source="2026-09-18-pattern-policy-v2.json",
        original_metrics=original["metrics"],
        results=rows,
        gross_buy_hold_return_pct=sum(gross.values()) / len(gross),
        gross_buy_hold_by_symbol=gross,
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
