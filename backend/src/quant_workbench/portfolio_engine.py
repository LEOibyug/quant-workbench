"""Synchronous minute execution with one cash ledger and optional capital rotation."""

import math
from collections import deque
from types import SimpleNamespace

import numpy as np
import pandas as pd

from quant_workbench.allocation import allocate
from quant_workbench.costs import estimate_round_trip
from quant_workbench.market_data import require_complete, schedule
from quant_workbench.statistical import bayesian_session_forecasts
from quant_workbench.strategies import (
    REFINED_STRATEGIES,
    REVERSION_GATE_STRATEGIES,
    SCALING_STRATEGIES,
    IntradayRules,
    basket_regime_gate,
)


def simulate_portfolio(
    frame, config, start, end, strategies=None, model=None, record_market=False, progress=None
):
    allocation = config.allocation
    cutoff = pd.Timestamp(start, tz="America/New_York").tz_convert("UTC")
    past = frame[frame.timestamp < cutoff].sort_values(["symbol", "timestamp"])
    if model is not None and hasattr(model, "seed_history"):
        model.seed_history(past, start)
    frame = require_complete(frame, start, end)
    symbols = sorted(frame.symbol.unique())
    if not symbols:
        raise ValueError("没有选择股票")
    strategies = {s: (strategies or {}).get(s, config.strategy) for s in symbols}
    strategies = {s: "sma" if v == "adaptive" else v for s, v in strategies.items()}
    full = pd.concat([past, frame], ignore_index=True)
    regime = basket_regime_gate(full, config)
    session_forecasts = (
        bayesian_session_forecasts(full, config)
        if "bayesian_session" in strategies.values()
        else {}
    )
    closes = {str(row.Index.date()): row.close for row in schedule(start, end).itertuples()}
    states = {}
    for s in symbols:
        rules = (
            IntradayRules(config, strategies[s], past[past.symbol == s], session_forecasts)
            if strategies[s] in REFINED_STRATEGIES
            else None
        )
        states[s] = SimpleNamespace(
            shares=0,
            basis=0.0,
            realized=0.0,
            flows=0.0,
            fees=0.0,
            impact=0.0,
            target=False,
            exit_reason=None,
            desired=0,
            weight=0.0,
            previous_volume=0.0,
            signal_time=None,
            prices=deque(maxlen=max(config.slow, allocation.lookback + 1)),
            pv=0.0,
            volume=0.0,
            count=0,
            opening_high=0.0,
            rules=rules,
            model={},
            fraction=1.0,
            lots=[],
            position_id=0,
            session_flows=0.0,
            rule_cash=0.0,
            candidate=False,
            diagnostic=None,
        )
    cash = peak = config.initial_cash
    fees = impact = turnover = 0.0
    portfolio_curve, trades, decisions, market_curve = [], [], [], []
    funnel = {
        s: dict(
            bars=0,
            rule_candidates=0,
            model_blocked_candidates=0,
            entry_fills=0,
            unfilled_entry_attempts=0,
            rule_rejections={},
        )
        for s in symbols
    }
    session = None
    day_initial = cash
    daily_turnover = 0.0
    day_halted = False
    history = deque(maxlen=allocation.lookback + 1)
    benchmark_capital = cash
    benchmark_opens = {}
    grouped = frame.groupby("timestamp", sort=True)
    total = len(grouped)
    for i, (ts, group) in enumerate(grouped):
        bars = {r.symbol: r for r in group.itertuples(index=False)}
        day = str(ts.tz_convert("America/New_York").date())
        close_time = closes[day]
        if day != session:
            if any(st.shares for st in states.values()):
                raise ValueError("日内组合前一交易日未清仓，不得隐式隔夜")
            session = day
            day_initial = cash
            daily_turnover = 0.0
            day_halted = False
            benchmark_capital = portfolio_curve[-1]["benchmark"] if portfolio_curve else cash
            benchmark_opens = {s: float(bars[s].open) for s in symbols}
            history.clear()  # Minute returns never include overnight jumps.
            for st in states.values():
                st.target = False
                st.exit_reason = None
                st.desired = 0
                st.weight = 0.0
                st.previous_volume = 0.0
                st.signal_time = None
                st.prices.clear()
                st.pv = st.volume = st.opening_high = 0.0
                st.count = 0
                st.session_flows = st.flows
                st.rule_cash = day_initial * allocation.max_weight
                st.lots = []
                if st.rules:
                    st.rules.reset(st.rule_cash)
        opening_equity = cash + sum(st.shares * bars[s].open for s, st in states.items())
        day_halted |= opening_equity <= day_initial * (1 - config.daily_loss_bps / 10000)
        orders = []
        for s, st in states.items():
            bar = bars[s]
            if st.signal_time is None:
                continue
            mandatory = bool(st.exit_reason or day_halted or ts >= close_time or not st.target)
            desired = 0 if mandatory else st.desired
            delta = desired - st.shares
            lot_index = None
            reason = st.exit_reason or (
                "portfolio_day_stop" if day_halted else "portfolio_rotation"
            )
            if ts >= close_time:
                reason = "session_flatten"
            if st.lots and st.shares and not mandatory:
                lot_index, quantity, reason = st.lots[0]
                delta = -min(quantity, st.shares)
                mandatory = True  # Strategy exits cannot be blocked by turnover controls.
            if not delta:
                continue
            buying = delta > 0
            if buying:
                if st.model and not st.model.get("allow_entry", False):
                    continue
                if st.shares and strategies[s] in SCALING_STRATEGIES and not st.rules.add_entry:
                    continue
                if (
                    not st.shares
                    and strategies[s] in REVERSION_GATE_STRATEGIES
                    and not regime.get(day, True)
                ):
                    continue
            if not mandatory and abs(delta) * bar.open / opening_equity < allocation.rebalance_band:
                continue
            cap = max(0, math.floor(st.previous_volume * config.participation))
            quantity = min(abs(delta), cap)
            if buying:
                if st.rules and st.rules.max_quantity is not None:
                    limit = (
                        st.rules.max_quantity
                        if strategies[s] in SCALING_STRATEGIES
                        else max(
                            0,
                            st.rules.max_quantity - st.shares,
                        )
                    )
                    quantity = min(quantity, limit)
                quantity = math.floor(quantity * st.fraction)
            if quantity:
                orders.append((buying, s, quantity, mandatory, lot_index, reason))
        # All sales settle into the same ledger before any purchase; purchases share cash pro rata.
        funding_ratio = None
        for buying, s, quantity, mandatory, lot_index, reason in sorted(orders):
            st, bar = states[s], bars[s]
            direction = 1 if buying else -1
            price = float(bar.open) * (
                1 + direction * (config.spread_bps / 2 + config.slippage_bps) / 10000
            )
            if not mandatory and not buying:
                limit = max(0, day_initial * allocation.max_daily_turnover - daily_turnover)
                quantity = min(quantity, math.floor(limit / price))
            if buying:
                if funding_ratio is None:
                    required = sum(
                        q
                        * float(bars[sym].open)
                        * (1 + (config.spread_bps / 2 + config.slippage_bps) / 10000)
                        + max(config.minimum_commission, q * config.commission_per_share)
                        for b, sym, q, *_ in orders
                        if b
                    )
                    turnover_room = max(
                        0, day_initial * allocation.max_daily_turnover - daily_turnover
                    )
                    funding_ratio = min(
                        1, cash / max(required, 1e-9), turnover_room / max(required, 1e-9)
                    )
                quantity = math.floor(quantity * funding_ratio)
                if st.rules and st.rules.pending_take:
                    cost = estimate_round_trip(bar.open, st.previous_volume, cash, config, quantity)
                    if (
                        cost["round_trip_bps"] is None
                        or st.rules.pending_take / bar.open * 10000
                        <= config.rule_cost_multiplier * cost["round_trip_bps"] + 1
                    ):
                        quantity = 0
                while (
                    quantity
                    and quantity * price
                    + max(
                        config.minimum_commission,
                        quantity * config.commission_per_share,
                    )
                    > cash
                ):
                    quantity -= 1
            if not quantity:
                funnel[s]["unfilled_entry_attempts"] += int(buying)
                continue
            fee = max(config.minimum_commission, quantity * config.commission_per_share)
            fee += 0 if buying else quantity * price * config.sell_fee_bps / 10000
            price_impact = quantity * abs(price - bar.open)
            realized = None
            if buying:
                if not st.shares:
                    st.position_id += 1
                st.basis += quantity * price + fee
                cash -= quantity * price + fee
                st.flows -= quantity * price + fee
                st.shares += quantity
                funnel[s]["entry_fills"] += 1
            else:
                cost_basis = st.basis * quantity / st.shares
                realized = quantity * price - fee - cost_basis
                st.realized += realized
                st.basis -= cost_basis
                st.shares -= quantity
                cash += quantity * price - fee
                st.flows += quantity * price - fee
                if st.rules and st.rules.lots:
                    # Keep staged lots consistent under both rule exits and portfolio rotations.
                    remaining = quantity
                    index = lot_index if lot_index is not None else 0
                    while remaining and st.rules.lots:
                        index = min(index, len(st.rules.lots) - 1)
                        amount = min(remaining, st.rules.lots[index]["qty"])
                        st.rules.lot_filled(index, amount)
                        remaining -= amount
                if not st.shares:
                    st.basis = 0.0
                    st.exit_reason = None
            if st.rules:
                st.rules.filled("buy" if buying else "sell", price, st.shares, quantity)
            st.fees += fee
            st.impact += price_impact
            fees += fee
            impact += price_impact
            daily_turnover += quantity * price
            turnover += quantity * price / opening_equity
            trades.append(
                dict(
                    timestamp=(ts - pd.Timedelta(minutes=1) + pd.Timedelta(seconds=1)).isoformat(),
                    signal_time=st.signal_time.isoformat(),
                    symbol=s,
                    side="buy" if buying else "sell",
                    quantity=quantity,
                    price=price,
                    fee=fee,
                    impact_cost=price_impact,
                    realized_pnl=realized,
                    position_after=st.shares,
                    cash_after=cash,
                    position_id=f"{s}-{st.position_id}",
                    reason=reason,
                )
            )
        if ts >= close_time and any(st.shares for st in states.values()):
            raise ValueError("组合尾盘流动性不足，未能按参与率清仓；本次结果无效")
        equity = cash + sum(st.shares * bars[s].close for s, st in states.items())
        peak = max(peak, equity)
        day_halted |= equity <= day_initial * (1 - config.daily_loss_bps / 10000)
        base, expected, cost_rates, current = {}, {}, {}, {}
        for s, st in states.items():
            bar = bars[s]
            st.prices.append(float(bar.close))
            st.count += 1
            st.pv += (bar.high + bar.low + bar.close) / 3 * bar.volume
            st.volume += bar.volume
            if st.count <= config.opening_minutes:
                st.opening_high = max(st.opening_high, bar.high)
            vwap = st.pv / st.volume if st.volume else bar.close
            average = st.basis / st.shares if st.shares else 0
            rule_cash = max(0, st.rule_cash + st.flows - st.session_flows)
            if st.rules:
                st.target, risk = st.rules.observe(bar, st.shares, average, rule_cash, close_time)
                if risk and st.shares:
                    st.exit_reason = risk
                st.lots = (
                    st.rules.lot_exits(bar)
                    if st.shares and strategies[s] in SCALING_STRATEGIES
                    else []
                )
            else:
                fast, slow = (
                    np.mean(list(st.prices)[-config.fast :]),
                    np.mean(list(st.prices)[-config.slow :]),
                )
                ready = len(st.prices) >= config.slow
                if strategies[s] == "sma":
                    st.target = ready and fast > slow
                elif strategies[s] == "opening_breakout":
                    st.target = (st.shares > 0 and bar.close >= vwap) or (
                        st.count > config.opening_minutes
                        and bar.close > st.opening_high
                        and ready
                        and fast > slow
                    )
                elif strategies[s] == "vwap_reversion":
                    st.target = (st.shares > 0 and bar.close < vwap) or (
                        ready and bar.close < vwap * (1 - config.reversion_bps / 10000)
                    )
                else:
                    raise ValueError(f"未知策略: {strategies[s]}")
            if st.shares and bar.close <= average * (1 - config.stop_loss_bps / 10000):
                st.exit_reason = "stop_loss"
            if st.shares and not st.target:
                st.exit_reason = st.exit_reason or strategies[s]
            if ts >= close_time - pd.Timedelta(minutes=config.flatten_minutes):
                st.target = False
                if st.shares:
                    st.exit_reason = "session_flatten"
            st.candidate = bool(
                st.target
                and (not st.shares or (strategies[s] in SCALING_STRATEGIES and st.rules.add_entry))
            )
            if model is not None:
                cost = estimate_round_trip(bar.close, bar.volume, rule_cash, config)
                st.model = model.predict(
                    dict(
                        symbol=s,
                        timestamp=ts.isoformat(),
                        round_trip_cost_bps=cost["round_trip_bps"],
                        recent_bars=[
                            dict(
                                timestamp=ts.isoformat(),
                                open=bar.open,
                                high=bar.high,
                                low=bar.low,
                                close=bar.close,
                                volume=int(bar.volume),
                            )
                        ],
                    )
                )
                st.fraction = st.model.get("risk_fraction", 1.0)
                if st.candidate and not st.model["allow_entry"]:
                    funnel[s]["model_blocked_candidates"] += 1
                    if not st.shares:
                        st.target = False
                    elif st.rules:
                        st.rules.add_entry = False
            funnel[s]["bars"] += 1
            funnel[s]["rule_candidates"] += int(st.candidate)
            if st.exit_reason or day_halted:
                st.target = False
            current[s] = st.shares * float(bar.close) / equity
            base[s] = min(1 / len(symbols), allocation.max_weight) if st.target else 0.0
            if model is not None and not st.model.get("allow_entry", False) and not st.shares:
                base[s] = 0.0
            expected[s] = float(st.model.get("expected_return_bps") or 0) / 10000
            cost_rates[s] = (
                config.spread_bps / 2 + config.slippage_bps + config.sell_fee_bps
            ) / 10000
            cost_rates[s] += max(
                config.minimum_commission,
                config.commission_per_share * equity * allocation.max_weight / bar.close,
            ) / max(equity * allocation.max_weight, 1)
            st.signal_time, st.previous_volume = ts, bar.volume
        history.append({s: float(bars[s].close) for s in symbols})
        interval = next(iter(states.values())).count
        if interval % allocation.rebalance_minutes == 0:
            returns = pd.DataFrame(history).pct_change(fill_method=None)
            targets, decision = allocate(
                allocation,
                symbols,
                returns,
                base,
                current,
                expected,
                cost_rates,
                getattr(getattr(model, "config", None), "horizon", 1),
            )
            decision["timestamp"] = ts.isoformat()
            decisions.append(decision)
            for s, st in states.items():
                st.weight = targets[s]
                st.desired = math.floor(equity * st.weight / bars[s].close)
        for st in states.values():
            if not st.target:
                st.desired = 0
                st.weight = 0
        assets = {
            s: dict(
                open=float(bars[s].open),
                high=float(bars[s].high),
                low=float(bars[s].low),
                close=float(bars[s].close),
                volume=float(bars[s].volume),
                shares=st.shares,
                market_value=st.shares * float(bars[s].close),
                weight=current[s],
                target_weight=st.weight,
                realized_pnl=st.realized,
                unrealized_pnl=st.shares * float(bars[s].close) - st.basis,
                fees=st.fees,
                impact_cost=st.impact,
                forecast=st.model or None,
            )
            for s, st in states.items()
        }
        point = dict(
            timestamp=ts.isoformat(),
            equity=equity,
            cash=cash,
            cash_weight=cash / equity,
            gross_exposure=(equity - cash) / equity,
            drawdown_pct=(1 - equity / peak) * 100,
            realized_pnl=sum(st.realized for st in states.values()),
            unrealized_pnl=sum(a["unrealized_pnl"] for a in assets.values()),
            fees=fees,
            impact_cost=impact,
            assets=assets,
            benchmark=benchmark_capital
            * np.mean([bars[s].close / benchmark_opens[s] for s in symbols]),
        )
        portfolio_curve.append(point)
        if progress is not None and (i % 20 == 0 or i == total - 1):
            progress(i + 1, total, [], trades)
    daily = (
        pd.Series(
            [p["equity"] for p in portfolio_curve],
            index=pd.to_datetime(
                [p["timestamp"] for p in portfolio_curve],
                utc=True,
            ),
        )
        .groupby(lambda ts: str(ts.tz_convert("America/New_York").date()))
        .last()
    )
    returns = (
        np.diff(np.r_[config.initial_cash, daily.to_numpy()])
        / np.r_[
            config.initial_cash,
            daily.to_numpy()[:-1],
        ]
    )
    pnl = equity - config.initial_cash
    closed = [t["realized_pnl"] for t in trades if t["side"] == "sell"]
    return dict(
        engine_version="minute-portfolio-v1",
        portfolio_enabled=True,
        allocation_decisions=decisions,
        portfolio_curve=portfolio_curve,
        market_curve=market_curve,
        trades=trades,
        curve=[
            {k: p[k] for k in ("timestamp", "equity", "benchmark", "drawdown_pct")}
            for p in portfolio_curve
        ],
        metrics=dict(
            initial_cash=config.initial_cash,
            final_equity=equity,
            net_profit=pnl,
            return_pct=pnl / config.initial_cash * 100,
            max_drawdown_pct=max(p["drawdown_pct"] for p in portfolio_curve),
            fees=fees,
            impact_cost=impact,
            trade_count=len(trades),
            turnover=turnover,
            trading_days=len(daily),
            pnl_before_modeled_costs=pnl + fees + impact,
            daily_sharpe=float(returns.mean() / returns.std(ddof=1) * np.sqrt(252))
            if len(returns) > 1 and returns.std(ddof=1) > 1e-12
            else None,
            win_rate_pct=float(np.mean(np.array(closed) > 0) * 100) if closed else None,
            mean_trade_pnl=float(np.mean(closed)) if closed else None,
            intraday_benchmark_return_pct=(
                portfolio_curve[-1]["benchmark"] / config.initial_cash - 1
            )
            * 100,
        ),
        positions=[dict(symbol=s, position=st.shares) for s, st in states.items()],
        contributions=[
            dict(
                symbol=s,
                net_profit=st.flows + st.shares * float(bars[s].close),
                strategy=strategies[s],
            )
            for s, st in states.items()
        ],
        daily_returns=[
            dict(date=d, return_pct=float(v * 100))
            for d, v in zip(daily.index, returns, strict=True)
        ],
        decision_funnel=funnel,
        model_audit=model.audit if model else [],
        model_statistics=model.stats if model else {},
        assumptions=[
            "组合共享资金；股票同步推进，使用上一分钟信号，次分钟开盘执行；先卖后买，买单按可用资金同比缩减",
            "资金分配不创造入场信号；原规则与模型仍控制交易资格；每日尾盘清仓，不隔夜、不借款",
            "成交量上限使用前一分钟量；策略退出、止损和尾盘清仓优先于组合换手预算，仍受流动性约束",
            "收缩协方差只使用已完成的同日分钟收益；调仓缓冲带与成本惩罚抑制微小换仓",
            "组合日亏损达到策略日损上限后停止买入；分钟回撤和成交不是逐笔实盘撮合",
            "买卖佣金按每次成交收取；价差滑点已含成交价；卖出胜率按成交笔数，非完整回合胜率",
        ],
    )
