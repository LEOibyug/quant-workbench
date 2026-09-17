"""Fixed-origin Alpaca historical bars; credentials only from server environment."""

import os
import re
import time

import httpx
import pandas as pd

from quant_workbench.market_data import MAX_ROWS, session_minutes
from quant_workbench.models import AlpacaInput


def _get(client, url, **kwargs):
    # Retry only transient transport failures, never authentication/permission responses.
    for attempt in range(3):
        try:
            return client.get(url, **kwargs)
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(0.25 * 2**attempt)


def fetch_alpaca(request: AlpacaInput) -> pd.DataFrame:
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise ValueError("请在后端环境设置APCA_API_KEY_ID和APCA_API_SECRET_KEY，勿上传凭证")
    if request.start >= request.end:
        raise ValueError("开始日期必须早于结束日期")
    symbols = sorted(set(s.strip().upper() for s in request.symbols))
    if any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", s) for s in symbols):
        raise ValueError("股票代码无效")
    start, end = str(request.start), str(request.end)
    expected = session_minutes(start, end)
    if len(expected) * len(symbols) > MAX_ROWS or len(expected) == 0:
        raise ValueError("下载范围过大或没有交易日，请缩小范围")
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Min",
        "start": start + "T00:00:00Z",
        "end": end + "T00:00:00Z",
        "adjustment": "raw",
        "feed": request.feed,
        "limit": 10000,
    }
    records, seen_tokens = [], set()
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for _ in range(500):
            try:
                response = _get(
                    client,
                    "https://data.alpaca.markets/v2/stocks/bars",
                    params=params,
                    headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ValueError("Alpaca请求失败，请检查网络、账户权限、feed与日期范围") from exc
            for symbol, bars in payload.get("bars", {}).items():
                if symbol not in symbols:
                    raise ValueError("供应商返回了未请求标的")
                for bar in bars:
                    records.append(
                        {
                            "timestamp": pd.Timestamp(bar["t"]) + pd.Timedelta(minutes=1),
                            "symbol": symbol,
                            "open": bar["o"],
                            "high": bar["h"],
                            "low": bar["l"],
                            "close": bar["c"],
                            "volume": bar["v"],
                        }
                    )
            if len(records) > MAX_ROWS * 3:
                raise ValueError("供应商数据超过安全上限，未保存截断数据，请缩小范围")
            token = payload.get("next_page_token")
            if not token:
                break
            if token in seen_tokens:
                raise ValueError("供应商分页token重复，未保存不完整数据")
            seen_tokens.add(token)
            params["page_token"] = token
        else:
            raise ValueError("下载超过分页上限，未保存截断数据")
    if not records:
        raise ValueError("该范围没有返回行情")
    frame = pd.DataFrame(records)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    return frame[frame.timestamp.isin(expected)].reset_index(drop=True)


def fetch_massive(request: AlpacaInput) -> pd.DataFrame:
    """Massive (formerly Polygon) custom aggregates, raw minute-start bars."""
    from urllib.parse import urlsplit

    key = os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
    if not key:
        raise ValueError("请在后端环境设置MASSIVE_API_KEY（兼容POLYGON_API_KEY）")
    symbols = sorted(set(s.strip().upper() for s in request.symbols))
    if any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", s) for s in symbols):
        raise ValueError("股票代码无效")
    expected = session_minutes(str(request.start), str(request.end))
    if len(expected) == 0 or len(expected) * len(symbols) > MAX_ROWS:
        raise ValueError("下载范围过大或没有交易日，请缩小范围")
    # Millisecond endpoints prevent date timezone ambiguity and exclude the right boundary.
    first_ms = int((expected[0] - pd.Timedelta(minutes=1)).timestamp() * 1000)
    last_ms = int((expected[-1] - pd.Timedelta(minutes=1)).timestamp() * 1000)
    records = []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for symbol in symbols:
            path = f"/v2/aggs/ticker/{symbol}/range/1/minute/{first_ms}/{last_ms}"
            url = "https://api.massive.com" + path
            params = {"adjusted": "false", "sort": "asc", "limit": 50000}
            visited = set()
            for _ in range(500):
                if url in visited:
                    raise ValueError("供应商分页URL重复，未保存不完整数据")
                visited.add(url)
                try:
                    response = _get(
                        client, url, params=params, headers={"Authorization": f"Bearer {key}"}
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("status") not in {"OK", "DELAYED"}:
                        raise ValueError("provider status error")
                    for bar in payload.get("results", []):
                        records.append(
                            {
                                "timestamp": pd.to_datetime(bar["t"], unit="ms", utc=True)
                                + pd.Timedelta(minutes=1),
                                "symbol": symbol,
                                "open": bar["o"],
                                "high": bar["h"],
                                "low": bar["l"],
                                "close": bar["c"],
                                "volume": bar["v"],
                            }
                        )
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    raise ValueError(
                        "Massive请求失败，请检查网络、订阅分钟历史权限与调用频率"
                    ) from exc
                if len(records) > MAX_ROWS * 3:
                    raise ValueError("供应商数据超过上限，请缩小范围；未保存截断结果")
                next_url = payload.get("next_url")
                if not next_url:
                    break
                parsed = urlsplit(next_url)
                page_path = re.fullmatch(
                    rf"/v2/aggs/ticker/{re.escape(symbol)}/range/1/minute/(\d+)/(\d+)",
                    parsed.path,
                )
                if (
                    parsed.scheme != "https"
                    or parsed.netloc != "api.massive.com"
                    or page_path is None
                    or not first_ms <= int(page_path[1]) <= int(page_path[2]) <= last_ms
                    or parsed.fragment
                ):
                    raise ValueError("供应商分页地址无效；凭证不会发送到其他地址")
                url, params = next_url, None
            else:
                raise ValueError("下载超过分页上限，未保存截断数据")
    if not records:
        raise ValueError("该范围没有返回行情")
    frame = pd.DataFrame(records)
    return frame[frame.timestamp.isin(expected)].reset_index(drop=True)


def provider_catalog() -> list[dict]:
    return [
        {
            "id": "alpaca",
            "name": "Alpaca",
            "configured": bool(
                os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY")
            ),
            "credentials": ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
            "feeds": ["iex", "sip"],
            "note": "IEX为单所行情，SIP需相应权限；分钟历史范围依账户套餐而定",
        },
        {
            "id": "massive",
            "name": "Massive / Polygon",
            "configured": bool(
                os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
            ),
            "credentials": ["MASSIVE_API_KEY"],
            "feeds": [],
            "note": "聚合分钟行情；历史范围与调用次数依订阅套餐而定",
        },
    ]


def fetch_provider(request) -> pd.DataFrame:
    adapters = {"alpaca": fetch_alpaca, "massive": fetch_massive}
    frame = adapters[request.provider](request)
    wanted = {s.strip().upper() for s in request.symbols}
    missing = wanted - set(frame.symbol)
    if missing:
        raise ValueError(f"供应商未返回这些股票的常规时段行情：{', '.join(sorted(missing))}")
    return frame
