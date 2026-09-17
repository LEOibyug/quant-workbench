"""Descriptive training-only profiles; suggestions are hypotheses, not fitted alpha."""

import numpy as np
import pandas as pd


def analyze_stocks(frame: pd.DataFrame) -> list[dict]:
    profiles = []
    for symbol, group in frame.groupby("symbol", sort=True):
        group = group.sort_values("timestamp").copy()
        group["session"] = group.timestamp.dt.tz_convert("America/New_York").dt.date
        returns = group.groupby("session").close.pct_change().dropna()
        daily = group.groupby("session").agg(
            first=("open", "first"),
            last=("close", "last"),
            high=("high", "max"),
            low=("low", "min"),
            volume=("volume", "sum"),
        )
        efficiency = (
            ((daily["last"] - daily["first"]).abs() / (daily.high - daily.low).replace(0, np.nan))
            .fillna(0)
            .mean()
        )
        suggestion = "opening_breakout" if efficiency >= 0.35 else "vwap_reversion"
        profiles.append(
            {
                "symbol": symbol,
                "sessions": len(daily),
                "average_daily_volume": float(daily.volume.mean()),
                "average_daily_dollar_volume": float(
                    (group.close * group.volume).groupby(group.session).sum().mean()
                ),
                "intraday_volatility_bps": float(returns.std(ddof=0) * 10000)
                if len(returns)
                else 0,
                "median_range_pct": float(
                    ((daily.high - daily.low) / daily["first"]).median() * 100
                ),
                "trend_efficiency": float(efficiency),
                "suggested_strategy": suggestion,
                "reason": "开发期日内方向效率≥0.35，测试开盘突破假设"
                if efficiency >= 0.35
                else "开发期日内方向效率<0.35，测试VWAP偏离回归假设",
                "spread_measured": False,
            }
        )
    return profiles
