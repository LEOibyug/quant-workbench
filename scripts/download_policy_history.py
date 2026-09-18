"""Bulk Alpaca daily history, split-adjusted, with exclusive cutoff and provenance."""

import argparse
import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd
from quant_workbench.daily_data import normalize_daily
from quant_workbench.provider_windows import quarter_windows
from quant_workbench.repository import Repository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="bfbd52245d674bd487bdd558295ad222")
    parser.add_argument("--start", default="2020-09-01")
    parser.add_argument("--end", default="2025-09-01")
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/models/conditional-policy-v2/history")
    )
    args = parser.parse_args()
    date.fromisoformat(args.start)
    cutoff = date.fromisoformat(args.end)
    if args.start >= args.end:
        raise ValueError("开始日期必须早于截止日期")
    if args.end > "2025-09-01":
        raise ValueError("训练历史不得超过2025-09-01")
    symbols = Repository().get("datasets", args.universe)["symbols"]
    headers = {
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    windows = list(quarter_windows(args.start, args.end))
    all_frames = []
    with httpx.Client(timeout=45) as client:
        for index, (start, end) in enumerate(windows, 1):
            cache = args.output / f"{start}-{end}-split.parquet"
            if cache.exists():
                frame = pd.read_parquet(cache)
            else:
                params = dict(
                    symbols=",".join(symbols),
                    timeframe="1Day",
                    start=str(start),
                    end=str(end),
                    adjustment="split",
                    feed="sip",
                    limit=10000,
                )
                rows = []
                seen = set()
                while True:
                    response = client.get(
                        "https://data.alpaca.markets/v2/stocks/bars", headers=headers, params=params
                    )
                    if response.status_code != 200:
                        raise ValueError(
                            f"Alpaca daily request failed: HTTP {response.status_code}"
                        )
                    payload = response.json()
                    for symbol, bars in payload.get("bars", {}).items():
                        if symbol not in symbols:
                            raise ValueError("Unexpected symbol")
                        for b in bars:
                            day = (
                                pd.Timestamp(b["t"])
                                .tz_convert("America/New_York")
                                .strftime("%Y-%m-%d")
                            )
                            if str(start) <= day < str(end):
                                rows.append(
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
                    token = payload.get("next_page_token")
                    if not token:
                        break
                    if token in seen:
                        raise ValueError("Repeated token")
                    seen.add(token)
                    params["page_token"] = token
                frame = normalize_daily(pd.DataFrame(rows))
                frame.to_parquet(cache, index=False)
            all_frames.append(frame)
            print(f"{index}/{len(windows)} {start}—{end}: {len(frame)} rows", flush=True)
    frame = normalize_daily(pd.concat(all_frames, ignore_index=True))
    assert frame.day.max() < args.end
    dest = args.output / "daily.parquet"
    frame.to_parquet(dest, index=False)
    metadata = dict(
        provider="alpaca",
        feed="sip",
        adjustment="split",
        start=args.start,
        end_exclusive=args.end,
        symbols=symbols,
        rows=len(frame),
        sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
        coverage={
            s: dict(start=g.day.min(), end=g.day.max(), rows=len(g))
            for s, g in frame.groupby("symbol")
        },
        limitation=("Current universe selected ex post; split adjustment retrieved today may "
                    "reflect later split factors; no dividend total return."),
    )
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    # Pre-cutoff raw prices align split-adjusted warmup to raw evaluation data.
    from quant_workbench.daily_providers import fetch_daily
    from quant_workbench.models import ProviderInput

    anchor_path = args.output / "raw-anchor.parquet"
    if not anchor_path.exists():
        anchors = fetch_daily(ProviderInput(
            symbols=symbols, start=cutoff - timedelta(days=7), end=cutoff,
            provider="alpaca", feed="sip",
        ))
        anchors.to_parquet(anchor_path, index=False)
    anchors = pd.read_parquet(anchor_path)
    if anchors.day.max() >= args.end or not set(symbols).issubset(set(anchors.symbol)):
        raise ValueError("原始价格锚点不符合截止日期或股票范围")
    print("Saved", len(frame), "rows", flush=True)


if __name__ == "__main__":
    main()
