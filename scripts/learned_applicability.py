"""Research-only causal expert suitability features and matured utility labels."""

import numpy as np
import pandas as pd
from quant_workbench.conditional_policy import decompose
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig

EXPERTS = ("cross_momentum", "channel_trend", "residual_reversal")
CLASSES = ("cash", *EXPERTS)


def prepare(frame):
    if not {"day", "symbol", "close", "open"}.issubset(frame.columns):
        raise ValueError("行情字段不完整")
    close = (
        frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    complete = close.notna().all(axis=1).to_numpy()
    bad = np.flatnonzero(~complete)
    if len(bad):
        close = close.iloc[bad[-1] + 1 :]
    if len(close) < 64:
        raise ValueError("完整股票池共同历史不足64个交易日")
    end = (pd.Timestamp(close.index[-1]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    expected = schedule(str(close.index[0]), end).index.strftime("%Y-%m-%d")
    if list(close.index.astype(str)) != list(expected):
        raise ValueError("完整股票池存在交易日缺口")
    if not np.isfinite(close.to_numpy()).all() or (close <= 0).any().any():
        raise ValueError("Invalid closing prices")
    frame = frame[frame.day.isin(close.index)]
    opens = frame.pivot(index="day", columns="symbol", values="open").reindex(
        index=close.index, columns=close.columns
    )
    if not np.isfinite(opens.to_numpy()).all() or (opens <= 0).any().any():
        raise ValueError("Invalid opening prices")
    maps = [rule_forecasts(frame, PositionConfig(model=m)) for m in EXPERTS]
    weights = np.zeros((len(close), len(close.columns), 3))
    for i, day in enumerate(close.index):
        for j, symbol in enumerate(close.columns):
            weights[i, j] = [m.get((str(day), symbol), {}).get("target_weight", 0) for m in maps]
    return close, opens.to_numpy(), weights


def feature(logs, weights, i, j):
    if i < 63:
        raise ValueError("64 observations required")
    return np.r_[decompose(logs[i - 63 : i + 1, j])[1], weights[i, j] > 0]


def utility_label(opens, weights, i, j, horizon=21, fee=0.0008):
    held = np.zeros(3)
    wealth = np.ones(3)
    for t in range(i, i + horizon):
        position = (weights[t, j] > 0).astype(float)
        wealth *= (
            1 + position * (opens[t + 2, j] / opens[t + 1, j] - 1) - abs(position - held) * fee
        )
        held = position
    wealth *= 1 - held * fee
    return int(np.argmax(np.r_[0.0, wealth - 1]))
