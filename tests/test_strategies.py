from collections import deque
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


def test_regime_pullback_recovery_and_falling_market_rejection():
    import numpy as np

    config = StrategyConfig(strategy="trend_pullback", fast=8, slow=21)
    rules = IntradayRules(config, "trend_pullback")
    prices = np.r_[np.linspace(100, 101.15, 57), 101.08, 101.02, 100.98, 101.13]
    observations = [bar(i, price) for i, price in enumerate(prices)]
    signal, target, mode = rules.regime_signal(observations, prices, 0.2, 100.8)
    assert signal and mode == "trend" and np.isclose(target, 0.6)
    falling = np.r_[np.linspace(101, 99, 60), 99.15]
    observations = [bar(i, price) for i, price in enumerate(falling)]
    rules.strategy = "regime_adaptive"
    assert rules.regime_signal(observations, falling, 0.2, 100)[0] is False
    # Exit mode is captured by the fill, not changed by later regime classification.
    rules.pending_mode = "range"
    rules.pending_distance, rules.pending_take = 1, 3
    rules.filled("buy", 100, 10)
    rules.pending_mode = "trend"
    assert rules.entry_mode == "range"


def test_intraday_momentum_enters_once_daily_inside_tail_window():
    from quant_workbench.engine import simulate
    from quant_workbench.market_data import session_minutes

    times = session_minutes("2024-01-03", "2024-01-05")
    # 无震荡上行：每天动量恒为正，唯一的入场约束应来自尾盘窗口与每日一次。
    # 足够的 bar 振幅让 ATR 成本门槛可被通过。
    values = [100 + i * 0.02 for i in range(len(times))]
    frame = pd.DataFrame(
        dict(
            timestamp=times,
            symbol="TEST",
            open=[v - 0.01 for v in values],
            high=[v + 0.5 for v in values],
            low=[v - 0.5 for v in values],
            close=values,
            volume=100_000,
        )
    )
    result = simulate(
        frame,
        StrategyConfig(
            strategy="intraday_momentum",
            momentum_threshold_bps=10,
            take_atr=2,
            stop_atr=2,
            max_daily_entries=1,
            cooldown_minutes=0,
            flatten_minutes=5,
            opening_minutes=15,
            max_hold_minutes=25,
        ),
        "2024-01-03",
        "2024-01-05",
    )
    buys = [trade for trade in result["trades"] if trade["side"] == "buy"]
    assert len(buys) == 2  # 每个交易日恰好一次
    for trade in buys:
        local = pd.Timestamp(trade["signal_time"]).tz_convert("America/New_York")
        assert local.hour == 15 and local.minute >= 30
    sells = [trade for trade in result["trades"] if trade["side"] == "sell"]
    assert len(sells) == 2  # 收盘强制平仓，不做提前退出
    assert all(sell["reason"] == "session_flatten" for sell in sells)


def test_basket_regime_gate_is_causal_and_conservative():
    from quant_workbench.strategies import basket_regime_gate

    days = pd.bdate_range("2024-01-02", periods=30, tz="UTC")
    rows = []
    for i, ts in enumerate(days):
        close = 100 * (1.002**i if i < 15 else 1.002**15 * 0.998 ** (i - 15))
        for symbol in ("AAA", "BBB"):
            rows.append(
                dict(
                    timestamp=ts + pd.Timedelta(hours=14, minutes=i % 60),
                    symbol=symbol,
                    open=close,
                    high=close * 1.001,
                    low=close * 0.999,
                    close=close,
                    volume=10_000,
                )
            )
    frame = pd.DataFrame(rows)
    config = StrategyConfig(
        regime_gate="drift", regime_window_days=5, regime_min_drift_bps=50
    )
    gate = basket_regime_gate(frame, config)
    assert len(gate) == 30
    assert not any(gate[f"{d.date()}"] for d in days[:5])  # 历史不足保守禁入
    assert gate[f"{days[10].date()}"]  # 上涨段放行
    assert not gate[f"{days[25].date()}"]  # 下跌段禁入
    # 因果性：改动未来数据不改变更早日期的门控值
    mutated = frame.copy()
    late = mutated.timestamp >= days[20]
    mutated.loc[late, "close"] *= 3
    gate2 = basket_regime_gate(mutated, config)
    assert all(gate[f"{d.date()}"] == gate2[f"{d.date()}"] for d in days[:15])
    assert StrategyConfig().regime_gate == "off"
    assert basket_regime_gate(frame, StrategyConfig()) == {}


def test_regime_gate_blocks_entries_but_not_exits():
    from quant_workbench.engine import simulate
    from quant_workbench.market_data import session_minutes

    times = session_minutes("2024-01-03", "2024-01-05")
    values = [100 - i * 0.03 for i in range(len(times))]  # 持续下跌 basket
    frame = pd.DataFrame(
        dict(
            timestamp=times,
            symbol="TEST",
            open=[v + 0.01 for v in values],
            high=[v + 0.5 for v in values],
            low=[v - 0.5 for v in values],
            close=values,
            volume=100_000,
        )
    )
    # 重新构造多日连续下跌：按天重置价格使每日 basket drift 为负
    frame["rank"] = frame.groupby(frame.timestamp.dt.date).cumcount()
    base = 100.0
    day_index = (frame.timestamp.dt.tz_convert("America/New_York").dt.date).factorize()[0]
    path = [base - 1.2 * d for d in day_index]
    frame["close"] = [p - 0.004 * r for p, r in zip(path, frame["rank"], strict=True)]
    for col, delta in (("open", 0.01), ("high", 0.5), ("low", -0.5)):
        frame[col] = frame["close"] + delta
    gated = simulate(
        frame,
        StrategyConfig(
            strategy="vwap_reversion",
            reversion_bps=70,
            stop_loss_bps=150,
            regime_gate="drift",
            regime_window_days=2,
            regime_min_drift_bps=50,
        ),
        "2024-01-03",
        "2024-01-05",
    )
    assert not [t for t in gated["trades"] if t["side"] == "buy"]
    assert gated["decision_funnel"]["TEST"].get("regime_blocked_entries", 0) >= 0
    # 无门控时同样的数据应产生买入（价格低于VWAP阈值）
    ungated = simulate(
        frame,
        StrategyConfig(strategy="vwap_reversion", reversion_bps=70, stop_loss_bps=150),
        "2024-01-03",
        "2024-01-05",
    )
    assert any(t["side"] == "buy" for t in ungated["trades"])


def _lot_rules(lot_breakeven_hold=True, **override):
    cfg = StrategyConfig(
        strategy="scaled_reversion",
        lot_breakeven_hold=lot_breakeven_hold,
        lot_patience_minutes=30,
        lot_hard_stop_atr=4.0,
        max_hold_minutes=120,
        fast=5,
        slow=10,
        **override,
    )
    rules = IntradayRules(cfg, "scaled_reversion")
    rules.reset(100000.0)
    return rules


def test_lot_breakeven_hold_blocks_then_admits_loss_exit():
    rules = _lot_rules()
    rules.lots = [
        dict(
            qty=10,
            entry_bar=1,
            stop_price=95.0,
            take_price=110.0,
            breakeven_price=100.6,
            hard_stop_price=92.0,
        )
    ]
    dip = SimpleNamespace(close=97.0, high=98.0, low=96.0, open=97.5, volume=1000)
    rules.count = 10  # 持有10分钟 < 耐心30：低于盈亏平衡也不卖
    assert rules.lot_exits(dip) == []
    rules.count = 40  # 耐心耗尽，但日内趋势未转弱：仍不卖
    assert rules.lot_exits(dip) == []
    # 快均线低于慢均线且跌破当日开盘 → 期望转差，允许认赔
    falling = deque(
        SimpleNamespace(close=99.0 - i * 0.5, open=99.5 - i * 0.5, high=100.0, low=98.0)
        for i in range(12)
    )
    rules.bars = falling
    assert rules.lot_exits(dip) == [(0, 10, "lot_patience_exit")]
    # 灾难止损不受耐心约束
    crash = SimpleNamespace(close=91.0, high=92.0, low=90.0, open=92.0, volume=1000)
    assert rules.lot_exits(crash) == [(0, 10, "lot_hard_stop")]
    # 关闭盈亏平衡持有时恢复常规止损
    plain = _lot_rules(lot_breakeven_hold=False)
    plain.lots = [dict(rules.lots[0], qty=10)]
    plain.count = 10
    deeper = SimpleNamespace(close=94.0, high=95.0, low=93.5, open=94.5, volume=1000)
    assert plain.lot_exits(deeper) == [(0, 10, "lot_stop")]


def test_tranche_uptrend_requirement_blocks_falling_day_entries():
    from quant_workbench.engine import simulate
    from quant_workbench.market_data import session_minutes

    times = session_minutes("2024-01-03", "2024-01-04")
    rank = range(len(times))
    values = [100 - 0.05 * i for i in rank]  # 持续下跌：日内无看涨趋势
    frame = pd.DataFrame(
        dict(
            timestamp=times,
            symbol="TEST",
            open=[v + 0.01 for v in values],
            high=[v + 0.6 for v in values],
            low=[v - 0.6 for v in values],
            close=values,
            volume=100_000,
        )
    )
    common = dict(
        strategy="scaled_reversion",
        reversion_bps=30,
        reversion_atr=1.0,
        stop_atr=2.0,
        max_scaling_lots=3,
        max_daily_entries=3,
        max_hold_minutes=120,
    )
    bullish_only = simulate(
        frame, StrategyConfig(**common, tranche_requires_uptrend=True),
        "2024-01-03", "2024-01-04",
    )
    assert not [t for t in bullish_only["trades"] if t["side"] == "buy"]
    unrestricted = simulate(
        frame, StrategyConfig(**common, tranche_requires_uptrend=False),
        "2024-01-03", "2024-01-04",
    )
    assert any(t["side"] == "buy" for t in unrestricted["trades"])
