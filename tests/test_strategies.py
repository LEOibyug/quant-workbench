from types import SimpleNamespace

import pandas as pd
from quant_workbench.models import StrategyConfig
from quant_workbench.strategies import IntradayRules


def bar(i, close=100, volume=100000):
    return SimpleNamespace(
        timestamp=pd.Timestamp("2024-01-03T14:31Z") + pd.Timedelta(minutes=i),
        open=close - 0.05,
        close=close,
        high=close + 0.1,
        low=close - 0.1,
        volume=volume,
    )


def test_refined_risk_exits_use_frozen_signal_atr_and_cooldown():
    cfg = StrategyConfig(max_hold_minutes=5, cooldown_minutes=10)
    rules = IntradayRules(cfg, "trend_breakout")
    rules.reset(10000)
    rules.pending_distance, rules.pending_take = 1, 3
    rules.filled("buy", 100, 50)
    close_time = pd.Timestamp("2024-01-03T21:00Z")
    assert rules.observe(bar(0, 100.5), 50, 100, 5000, close_time) == (True, None)
    # Price gains one risk unit, then trails by the original distance despite wide bar ranges.
    assert rules.observe(bar(1, 101.5), 50, 100, 5000, close_time) == (True, None)
    assert rules.observe(bar(2, 100.4), 50, 100, 5000, close_time) == (False, "atr_trailing")
    rules.filled("sell", 100.4, 0)
    assert rules.observe(bar(3, 102), 0, 0, 10020, close_time)[0] is False
    assert rules.last_exit == 4


def test_daily_loss_latches_and_time_exit():
    rules = IntradayRules(StrategyConfig(max_hold_minutes=5), "trend_breakout")
    close_time = pd.Timestamp("2024-01-03T21:00Z")
    rules.reset(10000)
    rules.pending_distance, rules.pending_take = 5, 10
    rules.filled("buy", 100, 50)
    assert rules.observe(bar(0, 97), 50, 100, 5000, close_time) == (False, "daily_loss_limit")
    rules.filled("sell", 97, 0)
    for i in range(1, 30):
        assert rules.observe(bar(i, 100 + i * 0.1), 0, 0, 10000, close_time)[0] is False
    rules.reset(10000)
    rules.pending_distance, rules.pending_take = 5, 10
    rules.filled("buy", 100, 50)
    for i in range(4):
        assert rules.observe(bar(i), 50, 100, 5000, close_time) == (True, None)
    assert rules.observe(bar(4), 50, 100, 5000, close_time) == (False, "time_exit")


def signal_bars(strategy):
    if strategy == "trend_breakout":
        values = [100 + (0.02 if i % 2 else -0.02) for i in range(30)] + [100.5]
    else:
        values = [100 + (0.15 if i % 2 else -0.15) for i in range(29)] + [98.9, 99]
    result = [bar(i, value) for i, value in enumerate(values)]
    result[-1].high = result[-1].close + 0.04
    result[-1].volume *= 2
    return result


def test_real_entry_signals_reject_expensive_trades_and_size_risk():
    for strategy in ("trend_breakout", "range_reversion"):
        cfg = StrategyConfig(strategy=strategy)
        rules = IntradayRules(cfg, strategy)
        expensive = IntradayRules(cfg.model_copy(update={"commission_per_share": 10}), strategy)
        for instance in (rules, expensive):
            instance.reset(100000)
        for observation in signal_bars(strategy):
            target, _ = rules.observe(observation, 0, 0, 100000, pd.Timestamp("2024-01-03T21:00Z"))
            rejected, _ = expensive.observe(
                observation, 0, 0, 100000, pd.Timestamp("2024-01-03T21:00Z")
            )
        assert target, strategy
        assert not rejected, strategy
        assert rules.max_quantity * rules.pending_distance <= 250
        assert rules.max_quantity > 0


def test_engine_refined_entry_next_bar_risk_sizing_and_partial_exit_latch():
    from quant_workbench.engine import simulate
    from quant_workbench.market_data import session_minutes

    times = session_minutes("2024-01-03", "2024-01-04")
    observations = signal_bars("trend_breakout")
    values = [vars(b) | {"symbol": "TEST"} for b in observations]
    for i in range(len(values), len(times)):
        values.append(vars(bar(i, 100.5 if i < 33 else 99)) | {"symbol": "TEST"})
    frame = pd.DataFrame(values)
    frame.loc[31:, "volume"] = 1000  # exit capacity is only 10 shares per later bar
    cfg = StrategyConfig(strategy="trend_breakout")
    result = simulate(frame, cfg, "2024-01-03", "2024-01-04")
    trades = result["trades"]
    assert trades[0]["side"] == "buy"
    assert trades[0]["signal_time"] == times[30].isoformat()
    assert pd.Timestamp(trades[0]["timestamp"]) > times[30]
    assert trades[0]["quantity"] < 1000  # binding risk cap, not cash or participation
    sells = [trade for trade in trades if trade["side"] == "sell"]
    assert len(sells) > 1
    assert sum(t["quantity"] for t in sells) == trades[0]["quantity"]
    assert all(t["reason"] == "atr_stop" for t in sells)
    assert result["positions"][0]["position"] == 0
