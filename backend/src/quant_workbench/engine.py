"""Deterministic completed-bar strategies with next-bar approximate fills."""

import math
from collections import deque

import numpy as np
import pandas as pd

from quant_workbench.costs import estimate_round_trip
from quant_workbench.market_data import require_complete, schedule
from quant_workbench.models import StrategyConfig

ENGINE_VERSION = "minute-v3-cost-edge"


def simulate(
    frame: pd.DataFrame,
    config: StrategyConfig,
    start: str,
    end: str,
    strategies: dict[str, str] | None = None,
    model_filter=None,
) -> dict:
    frame = require_complete(frame, start, end)
    symbols = sorted(frame.symbol.unique())
    if not symbols:
        raise ValueError("没有选择股票")
    times = pd.DatetimeIndex(frame.timestamp.unique()).sort_values()
    closes = {str(row.Index.date()): row.close for row in schedule(start, end).itertuples()}
    equity = np.zeros(len(times))
    benchmark = np.zeros(len(times))
    trades, positions, roundtrips, contributions = [], [], [], []
    fee_total, impact_total = 0.0, 0.0
    strategies = strategies or {}
    for symbol in symbols:
        bars = frame[frame.symbol == symbol].sort_values("timestamp")
        cash = config.initial_cash / len(symbols)
        initial = cash
        shares = 0
        basis = 0.0
        realized = 0.0
        entry_price = 0.0
        target = False
        exit_pending = False
        exit_reason = None
        signal_time = None
        previous_volume = 0.0
        session = None
        history = deque(maxlen=max(config.slow, 60))
        prices = deque(maxlen=config.slow)
        session_bars = 0
        opening_high = 0.0
        pv = 0.0
        total_volume = 0.0
        model_decision = {"allow_entry": False}
        strategy = strategies.get(symbol, config.strategy)
        if strategy == "adaptive":
            strategy = "sma"
        benchmark_capital = initial
        benchmark_open = float(bars.iloc[0].open)
        benchmark_value = initial
        for i, row in enumerate(bars.itertuples(index=False)):
            ts = row.timestamp
            day = str(ts.tz_convert("America/New_York").date())
            close_time = closes[day]
            if session != day:
                if shares:
                    raise ValueError("前一交易日未能完成清仓，不得隐式隔夜")
                benchmark_capital = benchmark_value
                benchmark_open = float(row.open)
                session, target, signal_time = day, False, None
                history.clear()
                prices.clear()
                opening_high, pv, total_volume, session_bars = 0.0, 0.0, 0.0, 0
                previous_volume = 0.0
            # A scheduled close exit is issued ahead of the final bar.
            flatten = ts >= close_time
            wanted = False if flatten or exit_pending else target
            fill_reason = "session_flatten" if flatten else (exit_reason or strategy)
            qty = 0
            side = None
            # Previous completed minute's volume avoids using future volume at the open.
            cap = max(0, math.floor(previous_volume * config.participation))
            if signal_time is not None:
                if shares and not wanted:
                    side, qty = "sell", min(shares, cap)
                elif wanted and not shares:
                    side = "buy"
                    price = row.open * (1 + (config.spread_bps / 2 + config.slippage_bps) / 10000)
                    qty = max(0, min(cap, math.floor(cash / price)))
                    while (
                        qty
                        and qty * price
                        + max(config.minimum_commission, qty * config.commission_per_share)
                        > cash
                    ):
                        qty -= 1
            if qty:
                direction = 1 if side == "buy" else -1
                price = row.open * (
                    1 + direction * (config.spread_bps / 2 + config.slippage_bps) / 10000
                )
                notional = qty * price
                commission = max(config.minimum_commission, qty * config.commission_per_share)
                regulatory = notional * config.sell_fee_bps / 10000 if side == "sell" else 0
                fee = commission + regulatory
                impact = qty * abs(price - row.open)
                fee_total += fee
                impact_total += impact
                if side == "buy":
                    cash -= notional + fee
                    shares += qty
                    basis = notional + fee
                    entry_price = price
                    realized = 0.0
                else:
                    cash += notional - fee
                    realized += notional - fee
                    shares -= qty
                    if shares == 0:
                        roundtrips.append(realized - basis)
                        exit_pending, exit_reason = False, None
                trades.append(
                    {
                        "timestamp": (
                            ts - pd.Timedelta(minutes=1) + pd.Timedelta(seconds=1)
                        ).isoformat(),
                        "signal_time": signal_time.isoformat(),
                        "symbol": symbol,
                        "side": side,
                        "quantity": qty,
                        "price": float(price),
                        "fee": float(fee),
                        "impact_cost": float(impact),
                        "reason": fill_reason,
                        "cash_after": float(cash),
                    }
                )
            if flatten and shares:
                raise ValueError(f"{symbol}尾盘流动性不足，无法按参与率限制清仓；本次结果无效")
            equity[i] += cash + shares * row.close
            benchmark_value = benchmark_capital * row.close / benchmark_open
            benchmark[i] += benchmark_value
            prices.append(float(row.close))
            session_bars += 1
            if session_bars <= config.opening_minutes:
                opening_high = max(opening_high, row.high)
            pv += ((row.high + row.low + row.close) / 3) * row.volume
            total_volume += row.volume
            vwap = pv / total_volume if total_volume > 0 else row.close
            fast = float(np.mean(list(prices)[-config.fast :]))
            slow = float(np.mean(prices))
            if strategy == "sma":
                target = len(prices) >= config.slow and fast > slow
            elif strategy == "opening_breakout":
                target = (shares > 0 and row.close >= vwap) or (
                    session_bars > config.opening_minutes
                    and row.close > opening_high
                    and len(prices) >= config.slow
                    and fast > slow
                )
            elif strategy == "vwap_reversion":
                target = (shares > 0 and row.close < vwap) or (
                    len(prices) >= config.slow
                    and row.close < vwap * (1 - config.reversion_bps / 10000)
                )
            else:
                raise ValueError(f"未知策略: {strategy}")
            if shares and row.close <= entry_price * (1 - config.stop_loss_bps / 10000):
                exit_pending, exit_reason = True, "stop_loss"
            if shares and not target and not exit_pending:
                exit_pending, exit_reason = True, strategy
            if exit_pending:
                target = False
            if ts >= close_time - pd.Timedelta(minutes=config.flatten_minutes):
                target = False
                if shares:
                    exit_pending, exit_reason = True, "session_flatten"
            history.append(
                {
                    "timestamp": ts.isoformat(),
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": int(row.volume),
                }
            )
            if model_filter is not None:
                estimated_cost = estimate_round_trip(row.close, row.volume, cash, config)
                model_decision = model_filter.predict(
                    {
                        "symbol": symbol,
                        "timestamp": ts.isoformat(),
                        "recent_bars": [history[-1]],
                        "round_trip_cost_bps": estimated_cost["round_trip_bps"],
                    }
                )
                # The model gates entries; risk/rule exits never need model approval.
                if target and not shares:
                    target = model_decision["allow_entry"]
            signal_time, previous_volume = ts, row.volume
        positions.append({"symbol": symbol, "position": shares, "cash": float(cash)})
        contributions.append(
            {"symbol": symbol, "net_profit": float(cash - initial), "strategy": strategy}
        )
    trades.sort(key=lambda x: (x["timestamp"], x["symbol"]))
    peaks = np.maximum.accumulate(np.r_[config.initial_cash, equity])[1:]
    drawdown = equity / peaks - 1
    daily = pd.Series(equity, index=times).groupby(times.tz_convert("America/New_York").date).last()
    daily_returns = (
        np.diff(np.r_[config.initial_cash, daily.to_numpy()])
        / np.r_[config.initial_cash, daily.to_numpy()[:-1]]
    )
    std = daily_returns.std(ddof=1) if len(daily_returns) > 1 else 0
    sharpe = float(daily_returns.mean() / std * np.sqrt(252)) if std > 1e-12 else None
    pnl = float(equity[-1] - config.initial_cash)
    return {
        "engine_version": ENGINE_VERSION,
        "metrics": {
            "initial_cash": config.initial_cash,
            "final_equity": float(equity[-1]),
            "net_profit": pnl,
            "return_pct": pnl / config.initial_cash * 100,
            "max_drawdown_pct": float(-drawdown.min() * 100),
            "daily_sharpe": sharpe,
            "fees": fee_total,
            "impact_cost": impact_total,
            "pnl_before_modeled_costs": pnl + fee_total + impact_total,
            "trade_count": len(trades),
            "roundtrips": len(roundtrips),
            "win_rate_pct": float(np.mean(np.array(roundtrips) > 0) * 100) if roundtrips else None,
            "mean_trade_pnl": float(np.mean(roundtrips)) if roundtrips else None,
            "trading_days": len(daily),
            "intraday_benchmark_return_pct": float((benchmark[-1] / config.initial_cash - 1) * 100),
        },
        "curve": [
            {
                "timestamp": t.isoformat(),
                "equity": float(e),
                "benchmark": float(b),
                "drawdown_pct": float(-d * 100),
            }
            for t, e, b, d in zip(times, equity, benchmark, drawdown, strict=True)
        ],
        "trades": trades,
        "positions": positions,
        "contributions": contributions,
        "daily_returns": [
            {"date": str(d), "return_pct": float(r * 100)}
            for d, r in zip(daily.index, daily_returns, strict=True)
        ],
        "assumptions": [
            "分钟Bar模拟；次分钟开盘价代理成交，名义延迟1秒，非真实逐笔撮合",
            "成交股数≤前一分钟成交量×参与率，未模拟真实盘口队列",
            "常规时段只做多、独立等额资金、不加杠杆、尾盘清仓；缺失分钟拒绝回测",
            "价差按半价差/边加收，滑点另计；佣金最低收费按成交事件计算",
            "VWAP使用典型价格×分钟成交量近似；基准为每日开盘买入、收盘卖出的无成本持有，日间复利、不隔夜",
            "未复权行情不计算跨日价差收益；当前未支持公司行动总回报或隔夜持仓",
            "成本前损益是同一成交路径费用加回，不是重新模拟的无成本策略",
            "入场成本预估按当前收盘与拟下单股数计算一买一卖；碎单退出和跳空可使真实成本更高",
            "模型预测下一分钟收盘收益；多分钟持仓的收益仍以实际模拟出场计算，预测不是利润保证",
        ],
        "model_audit": model_filter.audit if model_filter is not None else [],
        "model_statistics": model_filter.stats if model_filter is not None else {},
    }
