"""Validation for independently sourced daily OHLCV snapshots."""
import numpy as np
import pandas as pd
from quant_workbench.market_data import MAX_ROWS, schedule


def normalize_daily(frame):
    columns = ['day', 'symbol', 'open', 'high', 'low', 'close', 'volume']
    if not set(columns).issubset(frame.columns) or not 0 < len(frame) <= MAX_ROWS:
        raise ValueError('日线需包含 day,symbol,open,high,low,close,volume 且行数有效')
    df = frame[columns].copy()
    df['day'] = pd.to_datetime(df.day, format='%Y-%m-%d', errors='raise').dt.strftime('%Y-%m-%d')
    df['symbol'] = df.symbol.astype(str).str.strip().str.upper()
    if df.day.isna().any() or not df.symbol.str.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}').all() or df.symbol.nunique() > 20:
        raise ValueError('日线日期或股票代码无效，最多20个标的')
    values = df[columns[2:]].apply(pd.to_numeric, errors='raise')
    if not np.isfinite(values.to_numpy()).all() or (values.iloc[:, :4] <= 0).any().any() or (values.volume < 0).any():
        raise ValueError('日线价格或成交量无效')
    if (values.high < values[['open', 'close', 'low']].max(axis=1)).any() or (values.low > values[['open', 'close', 'high']].min(axis=1)).any():
        raise ValueError('日线OHLC范围不一致')
    if df.duplicated(['day', 'symbol']).any():
        raise ValueError('日线包含重复股票/日期')
    end = str((pd.Timestamp(df.day.max()) + pd.Timedelta(days=1)).date())
    days = set(schedule(df.day.min(), end).index.strftime('%Y-%m-%d'))
    if not set(df.day).issubset(days):
        raise ValueError('日线包含非交易日')
    df[columns[2:]] = values
    return df.sort_values(['day', 'symbol']).reset_index(drop=True)
