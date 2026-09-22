"""A completed stop is not a permanent stock ban or a portfolio halt reset."""

import numpy as np
import pandas as pd
import pytest
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig, simulate_positions


def bars():
    days = schedule("2024-01-02", "2024-03-01").index.strftime("%Y-%m-%d")
    prices = np.full(len(days), 100.0)
    prices[5:] = 85.0
    return pd.DataFrame(
        dict(
            day=days,
            symbol="A",
            open=prices,
            close=prices,
            high=prices,
            low=prices,
            volume=10_000_000,
        )
    )


@pytest.mark.parametrize("frequency", [1, 5])
@pytest.mark.parametrize("buffer", [None, "fixed", "risk", "boundary", "risk_boundary"])
def test_completed_stop_allows_new_signal(frequency, buffer):
    frame = bars()
    result = simulate_positions(
        frame,
        PositionConfig(
            model="equal_weight", rebalance_days=frequency, tranche_weight=0.2, max_drawdown_pct=30,
            portfolio_policy="banded" if buffer else "legacy", execution_buffer=buffer or "fixed"
        ),
        "2024-01-02",
        "2024-03-01",
        daily_bars=True,
    )
    stops = [t for t in result["trades"] if t["reason"] == "risk_exit"]
    assert stops and stops[0]["position_after"] == 0
    assert any(t["side"] == "buy" and t["date"] > stops[0]["date"] for t in result["trades"])


def test_portfolio_halt_remains_permanent():
    frame = bars()
    result = simulate_positions(
        frame,
        PositionConfig(
            model="equal_weight", rebalance_days=1, tranche_weight=0.2, max_drawdown_pct=2
        ),
        "2024-01-02",
        "2024-03-01",
        daily_bars=True,
    )
    halt = next(p["date"] for p in result["curve"] if p["halted"])
    assert not any(t["side"] == "buy" and t["date"] >= halt for t in result["trades"])


def test_partial_stop_keeps_selling_before_reentry():
    frame = bars()
    # Previous-session liquidity caps exit at 20 shares/day, below the holding.
    frame.loc[4:14, "volume"] = 780000
    result = simulate_positions(
        frame,
        PositionConfig(
            model="equal_weight", rebalance_days=1, tranche_weight=0.2, max_drawdown_pct=30
        ),
        "2024-01-02",
        "2024-03-01",
        daily_bars=True,
    )
    stops = [t for t in result["trades"] if t["reason"] == "risk_exit"]
    assert len(stops) > 1 and stops[0]["position_after"] > 0
    flat = next(t["date"] for t in stops if t["position_after"] == 0)
    assert not any(
        t["side"] == "buy" and stops[0]["date"] <= t["date"] <= flat for t in result["trades"]
    )
    assert any(t["side"] == "buy" and t["date"] > flat for t in result["trades"])
