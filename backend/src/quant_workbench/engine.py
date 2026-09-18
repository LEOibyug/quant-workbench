"""Deterministic completed-bar strategies with next-bar approximate fills."""

import math
from collections import deque

import numpy as np
import pandas as pd

from quant_workbench.costs import estimate_round_trip
from quant_workbench.market_data import require_complete, schedule
from quant_workbench.models import StrategyConfig
from quant_workbench.statistical import bayesian_session_forecasts
from quant_workbench.strategies import (
    REFINED_STRATEGIES,
    REVERSION_GATE_STRATEGIES,
    SCALING_STRATEGIES,
    IntradayRules,
    basket_regime_gate,
)

ENGINE_VERSION = "minute-v6-causal-regime-statistics"


def simulate(
    frame: pd.DataFrame,
    config: StrategyConfig,
    start: str,
    end: str,
    strategies: dict[str, str] | None = None,
    model_filter=None,
    record_market=False,
    progress=None,
) -> dict:
    cutoff = pd.Timestamp(start, tz="America/New_York").tz_convert("UTC")
    past = frame[frame.timestamp < cutoff].sort_values(["symbol", "timestamp"])
    if model_filter is not None and hasattr(model_filter, "seed_history"):
        model_filter.seed_history(past, start)
    frame = require_complete(frame, start, end)
    symbols = sorted(frame.symbol.unique())
    if not symbols:
        raise ValueError("没有选择股票")
    times = pd.DatetimeIndex(frame.timestamp.unique()).sort_values()
    closes = {str(row.Index.date()): row.close for row in schedule(start, end).itertuples()}
    # Include available pre-evaluation history, but the gate only reads prior closes.
    regime_ok = basket_regime_gate(pd.concat([past, frame], ignore_index=True), config)
    session_forecasts = (
        bayesian_session_forecasts(pd.concat([past, frame], ignore_index=True), config)
        if "bayesian_session" in {config.strategy, *(strategies or {}).values()} else {}
    )
    equity = np.zeros(len(times))
    benchmark = np.zeros(len(times))
    trades, positions, roundtrips, contributions = [], [], [], []
    market_curve = []
    decision_funnel = {}
    fee_total, impact_total = 0.0, 0.0
    strategies = strategies or {}
    for symbol_index, symbol in enumerate(symbols):
        bars = frame[frame.symbol == symbol].sort_values("timestamp")
        funnel = {
            "bars": 0,
            "rule_candidates": 0,
            "model_blocked_candidates": 0,
            "entry_fills": 0,
            "unfilled_entry_attempts": 0,
            "rule_rejections": {},
        }
        decision_funnel[symbol] = funnel
        cash = config.initial_cash / len(symbols)
        initial = cash
        shares = 0
        basis = 0.0
        realized = 0.0
        entry_price = 0.0
        entry_quantity = position_id = 0
        realized_pnl = 0.0
        symbol_fees = symbol_impact = 0.0
        equity_peak = initial
        pending_model_fraction = 1.0
        risk_scaled = (
            getattr(getattr(model_filter, "config", None), "decision_mode", "strict")
            in ("risk_scaled", "adaptive")
        )
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
        pending_lot_sells = []
        strategy = strategies.get(symbol, config.strategy)
        if strategy == "adaptive":
            strategy = "sma"
        rules = (
            IntradayRules(config, strategy, past[past.symbol == symbol], session_forecasts)
            if strategy in REFINED_STRATEGIES
            else None
        )
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
                pending_lot_sells = []
                history.clear()
                prices.clear()
                opening_high, pv, total_volume, session_bars = 0.0, 0.0, 0.0, 0
                previous_volume = 0.0
                if rules is not None:
                    rules.reset(cash)
            # A scheduled close exit is issued ahead of the final bar.
            flatten = ts >= close_time
            wanted = False if flatten or exit_pending else target
            if (
                wanted
                and not shares
                and regime_ok
                and strategy in REVERSION_GATE_STRATEGIES
                and not regime_ok.get(day, True)
            ):
                # 状态门控只禁止新开仓；持仓退出与收盘清仓不受影响。
                wanted = False
                funnel["regime_blocked_entries"] = funnel.get("regime_blocked_entries", 0) + 1
            fill_reason = "session_flatten" if flatten else (exit_reason or strategy)
            qty = 0
            side = None
            # Previous completed minute's volume avoids using future volume at the open.
            cap = max(0, math.floor(previous_volume * config.participation))
            if signal_time is not None:
                selling_lot = None
                if pending_lot_sells and shares and not exit_pending:
                    # 分批退出：只卖触发条件的批次，其余持仓保留。
                    lot_index, lot_qty, lot_reason = pending_lot_sells[0]
                    side, qty = "sell", min(lot_qty, shares, cap)
                    fill_reason, selling_lot = lot_reason, lot_index
                elif shares and not wanted:
                    side, qty = "sell", min(shares, cap)
                elif wanted and (
                    not shares or (strategy in SCALING_STRATEGIES and rules.add_entry)
                ):
                    side = "buy"
                    price = row.open * (1 + (config.spread_bps / 2 + config.slippage_bps) / 10000)
                    qty = max(0, min(cap, math.floor(cash / price)))
                    if rules is not None and rules.max_quantity is not None:
                        qty = min(qty, rules.max_quantity)
                    qty = math.floor(qty * pending_model_fraction)
                    if rules is not None and risk_scaled and qty:
                        # Minimum commissions rise per share at reduced size. Recheck the
                        # rule's actual frozen target distance before allowing the fill.
                        scaled_cost = estimate_round_trip(
                            row.open, previous_volume, cash, config, qty
                        )
                        if scaled_cost["round_trip_bps"] is None or (
                            rules.pending_take / row.open * 10000
                            <= config.rule_cost_multiplier * scaled_cost["round_trip_bps"] + 1
                        ):
                            qty = 0
                    while (
                        qty
                        and qty * price
                        + max(config.minimum_commission, qty * config.commission_per_share)
                        > cash
                    ):
                        qty -= 1
            if side == "buy" and not qty:
                funnel["unfilled_entry_attempts"] += 1
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
                symbol_fees += fee
                symbol_impact += impact
                trade_pnl = None
                fee_total += fee
                impact_total += impact
                if side == "buy":
                    funnel["entry_fills"] += 1
                    cash -= notional + fee
                    shares += qty
                    if shares == qty:
                        # 从空仓开立：与单批路径完全一致。
                        basis = notional + fee
                        entry_quantity = qty
                        entry_price = price
                        realized = 0.0
                    else:
                        # 分批加仓：成本与数量累加，均价供整体止损兜底参考。
                        basis += notional + fee
                        entry_quantity += qty
                        entry_price = basis / entry_quantity
                    position_id += 1
                else:
                    trade_pnl = notional - fee - basis * qty / entry_quantity
                    realized_pnl += trade_pnl
                    cash += notional - fee
                    realized += notional - fee
                    shares -= qty
                    if selling_lot is not None and rules is not None:
                        if rules.lot_filled(selling_lot, qty) or shares == 0:
                            pending_lot_sells.pop(0)
                    if shares == 0:
                        roundtrips.append(realized - basis)
                        exit_pending, exit_reason = False, None
                if rules is not None:
                    rules.filled(side, price, shares, qty)
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
                        "position_id": f"{symbol}-{position_id}",
                        "position_after": shares,
                        "realized_pnl": trade_pnl,
                        "model_risk_fraction": pending_model_fraction if side == "buy" else None,
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
            if rules is not None:
                target, risk_reason = rules.observe(row, shares, entry_price, cash, close_time)
                if shares and risk_reason and not exit_pending:
                    exit_pending, exit_reason = True, risk_reason
                elif strategy in SCALING_STRATEGIES and shares and not exit_pending:
                    pending_lot_sells = rules.lot_exits(row)
            elif strategy == "sma":
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
            if (
                shares
                and not exit_pending
                and row.close <= entry_price * (1 - config.stop_loss_bps / 10000)
            ):
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
            rule_candidate = bool(target and (
                not shares or (strategy in SCALING_STRATEGIES and rules.add_entry)
            ))
            if model_filter is not None:
                estimated_cost = estimate_round_trip(
                    row.close,
                    row.volume,
                    cash,
                    config,
                    rules.max_quantity if rules is not None else None,
                )
                model_decision = model_filter.predict(
                    {
                        "symbol": symbol,
                        "timestamp": ts.isoformat(),
                        "recent_bars": [history[-1]],
                        "round_trip_cost_bps": estimated_cost["round_trip_bps"],
                    }
                )
                # The model gates entries (including scaled tranches); exits never need it.
                if rule_candidate:
                    if not shares:
                        target = model_decision["allow_entry"]
                    elif not model_decision["allow_entry"]:
                        rules.add_entry = False
                    pending_model_fraction = model_decision.get("risk_fraction", 1.0)
            funnel["bars"] += 1
            if rule_candidate:
                funnel["rule_candidates"] += 1
                if model_filter is not None and not model_decision["allow_entry"]:
                    funnel["model_blocked_candidates"] += 1
            elif not shares and rules is not None:
                reason = rules.entry_diagnostic
                funnel["rule_rejections"][reason] = funnel["rule_rejections"].get(reason, 0) + 1
            if record_market:
                value = float(cash + shares * row.close)
                equity_peak = max(equity_peak, value)
                market_curve.append(
                    {
                        "timestamp": ts.isoformat(),
                        "symbol": symbol,
                        "open": float(row.open),
                        "high": float(row.high),
                        "low": float(row.low),
                        "close": float(row.close),
                        "volume": int(row.volume),
                        "shares": shares,
                        "cash": float(cash),
                        "equity": value,
                        "benchmark": float(benchmark_value),
                        "drawdown_pct": float((1 - value / equity_peak) * 100),
                        "realized_pnl": float(realized_pnl),
                        "unrealized_pnl": float(
                            shares * row.close - basis * shares / entry_quantity
                        )
                        if shares
                        else 0.0,
                        "position_id": f"{symbol}-{position_id}" if shares else None,
                        "fees": symbol_fees,
                        "impact_cost": symbol_impact,
                        "probability": model_decision.get("probability"),
                        "expected_return_bps": model_decision.get("expected_return_bps"),
                        "required_edge_bps": model_decision.get("required_edge_bps"),
                        "rule_candidate": rule_candidate,
                        "rule_reason": rules.entry_diagnostic if rules else None,
                        "model_risk_fraction": model_decision.get("risk_fraction"),
                        "model_allow_entry": model_decision.get("allow_entry")
                        if model_filter
                        else None,
                        "decision_reason": model_decision.get("reason") if model_filter else None,
                    }
                )
            if progress is not None and (i % 20 == 0 or i == len(bars) - 1):
                progress(
                    symbol_index * len(times) + i + 1,
                    len(times) * len(symbols),
                    market_curve,
                    trades,
                )
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
        "market_curve": market_curve,
        "decision_funnel": decision_funnel,
        "trades": trades,
        "positions": positions,
        "contributions": contributions,
        "daily_returns": [
            {"date": str(d), "return_pct": float(r * 100)}
            for d, r in zip(daily.index, daily_returns, strict=True)
        ],
        "assumptions": [
            "增强规则止损/止盈根据已完成分钟收盘触发，次分钟执行；风险预算不保证限制跳空损失",
            "分钟Bar模拟；次分钟开盘价代理成交，名义延迟1秒，非真实逐笔撮合",
            "成交股数≤前一分钟成交量×参与率，未模拟真实盘口队列",
            "常规时段只做多、独立等额资金、不加杠杆、尾盘清仓；缺失分钟拒绝回测",
            "价差按半价差/边加收，滑点另计；佣金最低收费按成交事件计算",
            "VWAP使用典型价格×分钟成交量近似；基准为每日开盘买入、收盘卖出的无成本持有，日间复利、不隔夜",
            "未复权行情不计算跨日价差收益；当前未支持公司行动总回报或隔夜持仓",
            "成本前损益是同一成交路径费用加回，不是重新模拟的无成本策略",
            "入场成本预估按当前收盘与拟下单股数计算一买一卖；碎单退出和跳空可使真实成本更高",
            "模型预测配置的h分钟收盘收益；多分钟持仓的收益仍以实际模拟出场计算，预测不是利润保证",
        ],
        "model_audit": model_filter.audit if model_filter is not None else [],
        "model_statistics": model_filter.stats if model_filter is not None else {},
    }
