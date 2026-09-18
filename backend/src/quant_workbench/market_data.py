"""Canonical minute-end US regular-session bars."""

from functools import lru_cache

import exchange_calendars as xcals
import numpy as np
import pandas as pd

COLUMNS = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
MAX_ROWS = 2_000_000


@lru_cache(maxsize=32)
def schedule(start: str, end: str) -> pd.DataFrame:
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    if start_ts >= end_ts or end_ts - start_ts > pd.Timedelta(days=3653):
        raise ValueError("日期范围无效，单个数据集最多10年")
    calendar = xcals.get_calendar(
        "XNYS", start=start_ts - pd.Timedelta(days=7), end=end_ts + pd.Timedelta(days=7)
    )
    return calendar.schedule.loc[start : str((end_ts - pd.Timedelta(days=1)).date())]


def session_minutes(start: str, end: str) -> pd.DatetimeIndex:
    parts = [
        pd.date_range(row.open + pd.Timedelta(minutes=1), row.close, freq="min")
        for row in schedule(start, end).itertuples()
    ]
    if not parts:
        return pd.DatetimeIndex([], tz="UTC")
    return parts[0].append(parts[1:])


def normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if not set(COLUMNS).issubset(frame.columns):
        raise ValueError("CSV必须包含 timestamp,symbol,open,high,low,close,volume")
    if frame.empty or len(frame) > MAX_ROWS:
        raise ValueError(f"数据集需包含1—{MAX_ROWS}行；请分批缩小股票或日期范围")
    df = frame[COLUMNS].copy()
    raw = df.timestamp.astype(str)
    if not raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True).all():
        raise ValueError("timestamp必须包含时区，如2024-01-03T14:31:00Z；表示分钟结束时间")
    df["timestamp"] = pd.to_datetime(raw, utc=True, format="mixed", errors="raise")
    if df.timestamp.isna().any() or not (df.timestamp == df.timestamp.dt.floor("min")).all():
        raise ValueError("时间必须精确到整分钟")
    df["symbol"] = df.symbol.astype(str).str.strip().str.upper()
    if not df.symbol.str.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}").all():
        raise ValueError("股票代码格式无效")
    if df.symbol.nunique() > 20:
        raise ValueError("单数据集最多20个标的")
    if df.duplicated(["symbol", "timestamp"]).any():
        raise ValueError("发现重复的股票/分钟记录，请先核实数据来源")
    values = df[COLUMNS[2:]].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("行情包含空值或非有限值")
    if (values.iloc[:, :4] <= 0).any().any() or (values.volume < 0).any():
        raise ValueError("价格必须大于0，成交量不能为负")
    if (values.volume != np.floor(values.volume)).any():
        raise ValueError("volume必须是成交股数整数")
    if (
        (values.high < values[["open", "close", "low"]].max(axis=1))
        | (values.low > values[["open", "close", "high"]].min(axis=1))
    ).any():
        raise ValueError("OHLC价格范围不一致")
    df[COLUMNS[2:]] = values
    local = df.timestamp.dt.tz_convert("America/New_York")
    start = str(local.min().date())
    end = str((local.max() + pd.Timedelta(days=1)).date())
    allowed = session_minutes(start, end)
    if not df.timestamp.isin(allowed).all():
        raise ValueError("含非XNYS常规交易时段数据；仅接收分钟结束时间，含半日市和夏令时")
    return df.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def require_complete(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    expected = session_minutes(start, end)
    if len(expected) == 0:
        raise ValueError("区间内没有交易日")
    selected = frame[frame.timestamp.isin(expected)].copy()
    symbols = sorted(frame.symbol.unique())
    for symbol in symbols:
        actual = pd.DatetimeIndex(selected.loc[selected.symbol == symbol, "timestamp"])
        if len(actual) != len(expected) or not actual.sort_values().equals(expected):
            raise ValueError(f"{symbol}在所选区间缺少完整分钟数据；首版不补造停牌或缺失行情")
    return selected.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def demo_data() -> pd.DataFrame:
    rng = np.random.default_rng(1709)
    times = session_minutes("2024-01-02", "2024-03-01")
    frames = []
    for i, symbol in enumerate(["NVDA", "TSLA", "AAPL", "AMD", "SOFI"]):
        count = len(times)
        increments = rng.normal(0, 0.0006 + i * 0.0001, count)
        increments += 0.00015 * np.sin(np.arange(count) / (80 + i * 10))
        close = (30 + 30 * i) * np.exp(np.cumsum(increments))
        opening = np.r_[close[0], close[:-1]]
        wiggle = rng.uniform(0.001, 0.02, count)
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": times,
                    "symbol": symbol,
                    "open": opening,
                    "high": np.maximum(opening, close) + wiggle,
                    "low": np.minimum(opening, close) - wiggle,
                    "close": close,
                    "volume": rng.integers(5000, 50000, count),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)
