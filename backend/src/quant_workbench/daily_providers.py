"""Daily OHLCV for independently run, published long-horizon strategies."""

import os
import re
from urllib.parse import urlsplit

import httpx
import pandas as pd

from quant_workbench.market_data import schedule
from quant_workbench.providers import _get


def fetch_daily(request, progress=None):
    sessions = schedule(str(request.start), str(request.end))
    if sessions.empty:
        raise ValueError("区间内没有交易日")
    symbols = sorted(set(request.symbols))
    if any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", s) for s in symbols):
        raise ValueError("股票代码无效")
    alpaca = request.provider == "alpaca"
    if alpaca:
        key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise ValueError("请配置 Alpaca 行情凭证")
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    else:
        key = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
        if not key:
            raise ValueError("请配置 Massive 行情凭证")
        headers = {"Authorization": f"Bearer {key}"}
    records = []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for symbol in symbols:
            if alpaca:
                url = "https://data.alpaca.markets/v2/stocks/bars"
                params = dict(
                    symbols=symbol, timeframe="1Day", start=str(request.start),
                    end=str(request.end), adjustment="raw", feed=request.feed, limit=10000,
                )
            else:
                first = int(pd.Timestamp(request.start, tz="America/New_York").timestamp()*1000)
                last = int(pd.Timestamp(request.end, tz="America/New_York").timestamp()*1000)-1
                path = f"/v2/aggs/ticker/{symbol}/range/1/day/{first}/{last}"
                url = "https://api.massive.com" + path
                params = {"adjusted": "false", "sort": "asc", "limit": 50000}
            seen = set()
            for _ in range(500):
                marker = (url, str(params))
                if marker in seen:
                    raise ValueError("日线分页重复，未采用不完整行情")
                seen.add(marker)
                try:
                    response = _get(client, url, params=params, headers=headers)
                    response.raise_for_status()
                    payload = response.json()
                    if not alpaca and payload.get("status") not in {"OK", "DELAYED"}:
                        raise ValueError("provider status error")
                    bars = payload.get("bars", {}).get(symbol, []) if alpaca else payload.get(
                        "results", [],
                    )
                    for bar in bars:
                        stamp = (pd.Timestamp(bar["t"]) if alpaca else
                                 pd.to_datetime(bar["t"], unit="ms", utc=True))
                        records.append(dict(
                            day=stamp.tz_convert("America/New_York").strftime("%Y-%m-%d"),
                            symbol=symbol, open=bar["o"], high=bar["h"], low=bar["l"],
                            close=bar["c"], volume=bar["v"],
                        ))
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    raise ValueError("日线获取失败，请检查供应商凭证、权限、网络和日期") from exc
                if progress:
                    progress(f"下载 {symbol} 日线", len(records), None, "条日线")
                if alpaca:
                    token = payload.get("next_page_token")
                    if not token:
                        break
                    params = {**params, "page_token": token}
                else:
                    next_url = payload.get("next_url")
                    if not next_url:
                        break
                    parsed = urlsplit(next_url)
                    match = re.fullmatch(
                        rf"/v2/aggs/ticker/{re.escape(symbol)}/range/1/day/(\d+)/(\d+)",
                        parsed.path,
                    )
                    if (parsed.scheme != "https" or parsed.netloc != "api.massive.com"
                            or not match or parsed.fragment
                            or not first <= int(match[1]) <= int(match[2]) <= last):
                        raise ValueError("日线分页地址无效")
                    url, params = next_url, None
            else:
                raise ValueError("日线超过分页上限，未采用截断数据")
    if not records:
        raise ValueError("所选区间没有日线行情")
    frame = pd.DataFrame(records)
    expected = set(sessions.index.strftime("%Y-%m-%d"))
    return frame[frame.day.isin(expected)].sort_values(["day", "symbol"]).reset_index(drop=True)
