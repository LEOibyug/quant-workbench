import pandas as pd
import pytest
from quant_workbench.engine import simulate
from quant_workbench.market_data import session_minutes
from quant_workbench.models import StrategyConfig


def bars(prices=None):
    times = session_minutes("2024-01-03", "2024-01-04")
    values = [100.0] * len(times) if prices is None else prices
    return pd.DataFrame(
        {
            "timestamp": times,
            "symbol": "TEST",
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": 100_000,
        }
    )


def test_costs_and_next_bar_fills_match_hand_calculation():
    frame = bars([100, 101, 102] + [110] * 387)
    result = simulate(
        frame,
        StrategyConfig(
            fast=2,
            slow=3,
            initial_cash=1000,
            spread_bps=0,
            slippage_bps=0,
            commission_per_share=0,
            minimum_commission=1,
            sell_fee_bps=0,
        ),
        "2024-01-03",
        "2024-01-04",
    )
    trades = result["trades"]
    assert trades[0]["side"] == "buy"
    assert trades[0]["price"] == 110
    assert trades[0]["quantity"] == 9  # (1000 - $1) / $110
    assert trades[0]["signal_time"] == "2024-01-03T14:33:00+00:00"
    assert trades[0]["timestamp"] == "2024-01-03T14:33:01+00:00"
    assert result["metrics"]["net_profit"] == -2
    assert result["metrics"]["fees"] == 2
    assert result["metrics"]["final_equity"] == 998


def test_close_schedule_uses_known_early_close_and_leaves_no_position():
    times = session_minutes("2024-11-29", "2024-11-30")
    frame = bars().iloc[: len(times)].copy()
    frame["timestamp"] = times
    for col in ["open", "high", "low", "close"]:
        frame[col] = [100 + i * 0.01 for i in range(len(times))]
    result = simulate(frame, StrategyConfig(fast=2, slow=3), "2024-11-29", "2024-11-30")
    assert result["trades"][-1]["timestamp"] == "2024-11-29T17:55:01+00:00"
    assert result["trades"][-1]["reason"] == "session_flatten"
    assert all(row["position"] == 0 for row in result["positions"])


def test_future_prices_cannot_change_earlier_trades():
    frame = bars([100 + i * 0.01 for i in range(390)])
    config = StrategyConfig(fast=2, slow=3)
    a = simulate(frame, config, "2024-01-03", "2024-01-04")
    for col in ["open", "high", "low", "close"]:
        frame.loc[200:, col] *= 3
    b = simulate(frame, config, "2024-01-03", "2024-01-04")
    cutoff = "2024-01-03T17:50:00+00:00"
    assert [t for t in a["trades"] if t["timestamp"] < cutoff] == [
        t for t in b["trades"] if t["timestamp"] < cutoff
    ]


def test_missing_minutes_rejected_no_fabricated_exit():
    with pytest.raises(ValueError, match="完整"):
        simulate(bars().iloc[:-1], StrategyConfig(), "2024-01-03", "2024-01-04")


def test_zero_volume_prevents_fills():
    frame = bars([100 + i * 0.01 for i in range(390)])
    frame["volume"] = 0
    result = simulate(frame, StrategyConfig(fast=2, slow=3), "2024-01-03", "2024-01-04")
    assert result["trades"] == []
    assert result["metrics"]["net_profit"] == 0


def test_partial_stop_exit_is_not_cancelled_by_price_rebound():
    frame = bars([99, 100, 101, 95, 101, 102] + [103 + i * 0.01 for i in range(384)])
    frame.loc[3, ["open", "high"]] = 101
    frame.loc[3:8, "volume"] = 1000
    result = simulate(
        frame,
        StrategyConfig(fast=2, slow=3, initial_cash=100_000, stop_loss_bps=100),
        "2024-01-03",
        "2024-01-04",
    )
    trades = result["trades"]
    first_buy = trades[0]["quantity"]
    sold = 0
    for trade in trades[1:]:
        if sold >= first_buy:
            break
        assert trade["side"] == "sell"
        assert trade["reason"] == "stop_loss"
        sold += trade["quantity"]
    assert sold == first_buy


def test_intraday_benchmark_does_not_treat_overnight_split_as_loss():
    first = bars()
    second = bars()
    second["timestamp"] = session_minutes("2024-01-04", "2024-01-05")
    second[["open", "high", "low", "close"]] = 10.0
    result = simulate(pd.concat([first, second]), StrategyConfig(), "2024-01-03", "2024-01-05")
    assert result["metrics"]["intraday_benchmark_return_pct"] == 0
    assert result["curve"][-1]["benchmark"] == 100_000
