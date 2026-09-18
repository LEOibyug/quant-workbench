"""Independent daily-position engine: overnight holdings and staged target-weight execution."""

import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from sklearn.linear_model import BayesianRidge
from sklearn.preprocessing import StandardScaler

from quant_workbench.allocation import AllocationConfig, allocate
from quant_workbench.daily_strategies import (
    MODELS as DAILY_RULE_MODELS,
)
from quant_workbench.daily_strategies import (
    cost_aware_targets,
    rule_forecasts,
)
from quant_workbench.market_data import require_complete, schedule
from quant_workbench.models import StrategyConfig


class PositionConfig(BaseModel):
    allocation: AllocationConfig = Field(default_factory=AllocationConfig)
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    model: Literal[
        "trend",
        "bayesian",
        "equal_weight",
        "cross_momentum",
        "channel_trend",
        "residual_reversal",
        "minimum_variance",
        "fixed_ensemble",
        "adaptive_specialist",
        "synthetic_regime",
        "generated_policy",
    ] = "bayesian"
    lookback: int = Field(default=20, ge=10, le=60)
    horizon: int = Field(default=5, ge=1, le=20)
    rebalance_days: int = Field(default=5, ge=1, le=20)
    confidence: float = Field(default=0.5, ge=0, le=3)
    tranche_weight: float = Field(default=0.05, gt=0, le=0.2)
    max_weight: float = Field(default=0.2, gt=0, le=0.5)
    capital_mode: Literal["signal_budget", "risk_budget"] = "signal_budget"
    classifier_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    portfolio_policy: Literal["legacy", "cost_aware"] = "legacy"
    entry_band: float | None = Field(default=None, ge=0, le=0.2)
    daily_vol_target: float = Field(default=0.015, gt=0, le=0.05)
    stop_loss_pct: float = Field(default=10, ge=2, le=30)
    max_drawdown_pct: float = Field(default=10, ge=2, le=30)
    costs: StrategyConfig = Field(default_factory=StrategyConfig)


def daily_inputs(frame):
    frame = frame.sort_values(["symbol", "timestamp"])
    day = frame.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    daily = (
        frame.assign(day=day)
        .groupby(["day", "symbol"], as_index=False)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            last_volume=("volume", "last"),
        )
    )
    for _, group in daily.groupby("symbol"):
        gap = group.open.to_numpy()[1:] / group.close.to_numpy()[:-1]
        if np.any((gap < 0.65) | (gap > 1.5)):
            raise ValueError("检测到疑似拆股或极端隔夜跳变；跨日回测需先核验公司行动数据")
    return daily


def daily_forecasts(daily, config):
    """Each forecast fits only labels whose target day has already closed."""
    if config.model in DAILY_RULE_MODELS:
        return rule_forecasts(daily, config)
    symbols = sorted(daily.symbol.unique())
    days = sorted(daily.day.unique())
    rows = []
    for symbol, group in daily.groupby("symbol"):
        group = group.sort_values("day").reset_index(drop=True)
        close = group.close.to_numpy()
        for i in range(config.lookback, len(group)):
            returns = np.diff(np.log(close[i - config.lookback : i + 1]))
            volatility = max(float(returns.std()), 1e-6)
            features = [
                math.log(close[i] / close[i - 5]),
                float(returns.sum()),
                volatility,
                close[i] / close[i - config.lookback : i + 1].mean() - 1,
                *[float(symbol == s) for s in symbols],
            ]
            target_index = i + config.horizon
            target_day = group.iloc[target_index].day if target_index < len(group) else None
            target = (
                math.log(close[target_index] / group.iloc[i + 1].open) * 10000
                if target_day is not None
                else None
            )
            rows.append(
                dict(
                    day=group.iloc[i].day,
                    symbol=symbol,
                    x=features,
                    y=target,
                    target_day=target_day,
                    volatility=volatility,
                    mean=float(returns.mean()) * config.horizon * 10000,
                    uncertainty=volatility * math.sqrt(config.horizon) * 10000,
                )
            )
    output = {}
    for i, day in enumerate(days):
        today = [row for row in rows if row["day"] == day]
        if not today:
            continue
        if config.model == "bayesian":
            lower = days[max(0, i - 60)]
            train = [
                row
                for row in rows
                if row["target_day"] is not None
                and row["target_day"] <= day
                and row["day"] >= lower
            ]
            if len(train) < 50:
                continue
            scaler = StandardScaler()
            model = BayesianRidge().fit(
                scaler.fit_transform([row["x"] for row in train]),
                [row["y"] for row in train],
            )
            means, uncertainties = model.predict(
                scaler.transform([row["x"] for row in today]),
                return_std=True,
            )
            last_target = max(row["target_day"] for row in train)
        else:
            means = [row["mean"] for row in today]
            uncertainties = [row["uncertainty"] for row in today]
            last_target = None
        for row, mean, uncertainty in zip(today, means, uncertainties, strict=True):
            output[(day, row["symbol"])] = dict(
                mean_bps=float(mean),
                uncertainty_bps=float(uncertainty),
                volatility=row["volatility"],
                last_training_target=last_target,
            )
    return output


def simulate_positions(frame, config, start, end, progress=None, *, daily_bars=False):
    if config.model == "generated_policy":
        from quant_workbench.generated_policy import artifact_digest

        digest = artifact_digest()
        if config.classifier_sha256 and digest != config.classifier_sha256:
            raise ValueError("分类器文件已改变，与冻结版本不一致；请恢复原模型或新建研究")
        config = config.model_copy(update={"classifier_sha256": digest})
    if daily_bars:
        daily = frame[frame.day < end].copy()
        sessions = schedule(start, end)
        expected = set(sessions.index.strftime("%Y-%m-%d"))
        if not expected or daily.empty:
            raise ValueError("区间内没有日线行情")
        if daily.duplicated(["day", "symbol"]).any():
            raise ValueError("日线行情存在重复日期")
        values = daily[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
        if (
            not np.isfinite(values).all()
            or (values[:, :4] <= 0).any()
            or (values[:, 4] < 0).any()
            or (daily.high < daily[["open", "close", "low"]].max(axis=1)).any()
            or (daily.low > daily[["open", "close", "high"]].min(axis=1)).any()
        ):
            raise ValueError("日线价格或成交量无效")
        daily = daily.sort_values(["day", "symbol"])
        for symbol, group in daily.groupby("symbol"):
            if not expected.issubset(set(group.day)):
                raise ValueError(f"{symbol}在所选区间缺少交易日日线，请检查上市日期或数据权限")
            gap = group.open.to_numpy()[1:] / group.close.to_numpy()[:-1]
            if np.any((gap < 0.65) | (gap > 1.5)):
                raise ValueError("检测到疑似拆股或极端隔夜跳变；跨日回测需先核验公司行动数据")
        all_sessions = schedule(str(daily.day.min()), end)
        minutes = (all_sessions.close - all_sessions.open).dt.total_seconds() / 60
        durations = dict(zip(all_sessions.index.strftime("%Y-%m-%d"), minutes, strict=True))
        # This is an explicit daily-volume proxy, never the current day's future volume.
        daily["last_volume"] = daily.volume / daily.day.map(durations)
        if daily.last_volume.isna().any():
            raise ValueError("日线日期不属于交易日")
    else:
        require_complete(frame, start, end)
        # Do not let post-evaluation observations enter this experiment at all.
        cutoff = pd.Timestamp(end, tz="America/New_York").tz_convert("UTC")
        daily = daily_inputs(frame[frame.timestamp < cutoff])
    forecasts = daily_forecasts(daily, config) if config.model != "equal_weight" else {}
    symbols = sorted(daily.symbol.unique())
    pivot = {day: group.set_index("symbol") for day, group in daily.groupby("day")}
    days = sorted(day for day in pivot if start <= day < end)
    costs = config.costs
    pooled_execution = config.allocation.enabled or config.portfolio_policy == "cost_aware"
    cash = peak = costs.initial_cash
    shares = {s: 0 for s in symbols}
    basis = {s: 0.0 for s in symbols}
    flows = {s: 0.0 for s in symbols}
    targets = {s: 0.0 for s in symbols}
    target_shares = {s: 0 for s in symbols}
    forced_exit = {s: False for s in symbols}
    halted = False
    allocation_decisions = []
    allocation_returns = daily.pivot(index="day", columns="symbol", values="close").pct_change(
        fill_method=None
    )
    realized = {s: 0.0 for s in symbols}
    symbol_fees = {s: 0.0 for s in symbols}
    symbol_impact = {s: 0.0 for s in symbols}
    turnover_total = 0.0
    trades, curve, signals = [], [], []
    fees = impact_total = 0.0
    previous = None
    for i, day in enumerate(days):
        prices = pivot[day]
        daily_turnover = 0.0
        if previous is not None:
            opening_equity = cash + sum(shares[s] * float(prices.loc[s, "open"]) for s in symbols)
            halted = halted or opening_equity <= peak * (1 - config.max_drawdown_pct / 100)
            for symbol in symbols:
                if shares[symbol] and float(prices.loc[symbol, "open"]) <= (
                    basis[symbol] * (1 - config.stop_loss_pct / 100)
                ):
                    forced_exit[symbol] = True
                if halted or forced_exit[symbol]:
                    targets[symbol] = 0.0
                    target_shares[symbol] = 0
            # Sell first; reallocate only available cash, with no margin or short positions.
            orders = []
            for symbol in symbols:
                price = float(prices.loc[symbol, "open"])
                desired = target_shares[symbol]
                delta = desired - shares[symbol]
                step = math.floor(opening_equity * config.tranche_weight / price)
                if delta < 0 and (halted or forced_exit[symbol]):
                    step = shares[symbol]  # Hard risk exits override staging, not liquidity.
                cap = math.floor(
                    float(pivot[previous].loc[symbol, "last_volume"]) * costs.participation
                )
                quantity = min(abs(delta), step, cap)
                if pooled_execution and desired > 0 and not forced_exit[symbol]:
                    band = (
                        config.entry_band
                        if shares[symbol] == 0 and delta > 0 and config.entry_band is not None
                        else config.allocation.rebalance_band
                    )
                    if abs(delta) * price / opening_equity < band:
                        quantity = 0
                if quantity:
                    orders.append((delta > 0, symbol, quantity))
            funding_ratio = None
            sale_ratio = 1.0
            if config.portfolio_policy == "cost_aware":
                sale_value = sum(
                    q * float(prices.loc[s, "open"])
                    for buying, s, q in orders
                    if not buying and not (halted or forced_exit[s])
                )
                sale_ratio = min(
                    1, opening_equity * config.allocation.max_daily_turnover / max(sale_value, 1e-9)
                )
            for buying, symbol, quantity in sorted(orders):
                raw = float(prices.loc[symbol, "open"])
                impact = raw * (costs.spread_bps / 2 + costs.slippage_bps) / 10000
                price = raw + impact if buying else raw - impact
                risk_exit = halted or forced_exit[symbol]
                if config.portfolio_policy == "cost_aware" and not buying and not risk_exit:
                    quantity = math.floor(quantity * sale_ratio)
                if pooled_execution and not risk_exit and not buying:
                    remaining = max(
                        0, opening_equity * config.allocation.max_daily_turnover - daily_turnover
                    )
                    quantity = min(quantity, math.floor(remaining / price))
                if buying:
                    if funding_ratio is None:
                        needed = sum(
                            q
                            * float(prices.loc[s, "open"])
                            * (1 + (costs.spread_bps / 2 + costs.slippage_bps) / 10000)
                            + max(costs.minimum_commission, q * costs.commission_per_share)
                            for b, s, q in orders
                            if b
                        )
                        turnover_room = max(
                            0,
                            opening_equity * config.allocation.max_daily_turnover - daily_turnover,
                        )
                        funding_ratio = (
                            min(
                                1,
                                max(
                                    0,
                                    cash
                                    - (
                                        opening_equity * 0.05
                                        if config.portfolio_policy == "cost_aware"
                                        else 0
                                    ),
                                )
                                / max(needed, 1e-9),
                                turnover_room / max(needed, 1e-9),
                            )
                            if pooled_execution
                            else 1
                        )
                    quantity = min(
                        math.floor(quantity * funding_ratio), max(0, math.floor(cash / price))
                    )
                    while (
                        quantity
                        and quantity * price
                        + max(
                            costs.minimum_commission,
                            quantity * costs.commission_per_share,
                        )
                        > cash
                    ):
                        quantity -= 1
                if not quantity:
                    continue
                fee = max(costs.minimum_commission, quantity * costs.commission_per_share)
                fee += 0 if buying else quantity * price * costs.sell_fee_bps / 10000
                trade_pnl = None
                if buying:
                    basis[symbol] = (basis[symbol] * shares[symbol] + quantity * price + fee) / (
                        shares[symbol] + quantity
                    )
                    shares[symbol] += quantity
                    cash -= quantity * price + fee
                    flows[symbol] -= quantity * price + fee
                else:
                    trade_pnl = quantity * (price - basis[symbol]) - fee
                    realized[symbol] += trade_pnl
                    shares[symbol] -= quantity
                    cash += quantity * price - fee
                    flows[symbol] += quantity * price - fee
                    if not shares[symbol]:
                        basis[symbol] = 0.0
                fees += fee
                symbol_fees[symbol] += fee
                symbol_impact[symbol] += quantity * impact
                impact_total += quantity * impact
                daily_turnover += quantity * price
                turnover_total += quantity * price / opening_equity
                trades.append(
                    dict(
                        date=day,
                        signal_date=previous,
                        symbol=symbol,
                        side="buy" if buying else "sell",
                        quantity=quantity,
                        price=price,
                        fee=fee,
                        impact_cost=quantity * impact,
                        realized_pnl=trade_pnl,
                        position_after=shares[symbol],
                        reason="risk_exit" if halted or forced_exit[symbol] else "staged_rebalance",
                    )
                )
        equity = cash + sum(shares[s] * float(prices.loc[s, "close"]) for s in symbols)
        peak = max(peak, equity)
        halted = halted or equity <= peak * (1 - config.max_drawdown_pct / 100)
        if i % config.rebalance_days == 0:
            for symbol in symbols:
                forecast = forecasts.get((day, symbol))
                close = float(prices.loc[symbol, "close"])
                quantity = max(1, math.floor(equity * config.tranche_weight / close))
                cost_bps = 2 * (costs.spread_bps / 2 + costs.slippage_bps) + costs.sell_fee_bps
                cost_bps += (
                    2
                    * max(
                        costs.minimum_commission,
                        quantity * costs.commission_per_share,
                    )
                    / (quantity * close)
                    * 10000
                )
                edge = (
                    forecast.get("mean_bps", 0)
                    - config.confidence * forecast.get("uncertainty_bps", 0)
                    if forecast
                    else -math.inf
                )
                weight = (
                    (
                        config.max_weight
                        if config.capital_mode == "risk_budget" and config.allocation.enabled
                        else min(config.max_weight, 1 / len(symbols))
                    )
                    * min(
                        1,
                        config.daily_vol_target / forecast["volatility"],
                    )
                    if forecast and edge > 1.5 * cost_bps
                    else 0.0
                )
                if config.model in DAILY_RULE_MODELS:
                    weight = forecast["target_weight"] if forecast else 0.0
                if config.model == "equal_weight":
                    weight = min(config.max_weight, 1 / len(symbols))
                targets[symbol] = weight
                target_shares[symbol] = math.floor(equity * weight / close)
                signals.append(
                    dict(date=day, symbol=symbol, target_weight=weight, forecast=forecast)
                )
            if config.allocation.enabled:
                eligible = {s: (0.0 if halted or forced_exit[s] else targets[s]) for s in symbols}
                current = {s: shares[s] * float(prices.loc[s, "close"]) / equity for s in symbols}
                expected = {
                    s: (
                        forecasts[(day, s)].get("mean_bps", 0)
                        - config.confidence * forecasts[(day, s)].get("uncertainty_bps", 0)
                    )
                    / 10000
                    if (day, s) in forecasts
                    else 0.0
                    for s in symbols
                }
                cost_rates = {
                    s: (costs.spread_bps / 2 + costs.slippage_bps + costs.sell_fee_bps) / 10000
                    + max(
                        costs.minimum_commission,
                        costs.commission_per_share
                        * equity
                        * config.tranche_weight
                        / float(prices.loc[s, "close"]),
                    )
                    / max(equity * config.tranche_weight, 1)
                    for s in symbols
                }
                targets, decision = allocate(
                    config.allocation,
                    symbols,
                    allocation_returns.loc[:day],
                    eligible,
                    current,
                    expected,
                    cost_rates,
                    config.horizon,
                )
                decision["date"] = day
                allocation_decisions.append(decision)
                for s in symbols:
                    target_shares[s] = math.floor(
                        equity * targets[s] / float(prices.loc[s, "close"])
                    )

            if config.portfolio_policy == "cost_aware":
                current = {s: shares[s] * float(prices.loc[s, "close"]) / equity for s in symbols}
                rates = {
                    s: (costs.spread_bps / 2 + costs.slippage_bps + costs.sell_fee_bps) / 10000
                    + max(
                        costs.minimum_commission,
                        costs.commission_per_share
                        * equity
                        * config.tranche_weight
                        / float(prices.loc[s, "close"]),
                    )
                    / max(equity * config.tranche_weight, 1)
                    for s in symbols
                }
                targets, decision = cost_aware_targets(
                    symbols,
                    allocation_returns.loc[:day],
                    {s: 0.0 if halted or forced_exit[s] else targets[s] for s in symbols},
                    current,
                    rates,
                    min(config.max_weight, 0.2),
                    config.rebalance_days,
                )
                decision["date"] = day
                allocation_decisions.append(decision)
                for s in symbols:
                    target_shares[s] = math.floor(
                        equity * targets[s] / float(prices.loc[s, "close"])
                    )

        for symbol in symbols:
            if shares[symbol] and float(prices.loc[symbol, "close"]) <= (
                basis[symbol] * (1 - config.stop_loss_pct / 100)
            ):
                forced_exit[symbol] = True
            elif not shares[symbol] and targets[symbol] == 0:
                forced_exit[symbol] = False
            if halted or forced_exit[symbol]:
                targets[symbol] = 0.0
                target_shares[symbol] = 0
        curve.append(
            dict(
                date=day,
                equity=equity,
                cash=cash,
                drawdown_pct=(1 - equity / peak) * 100,
                gross_exposure=(equity - cash) / equity,
                halted=halted,
                positions=dict(shares),
                cash_weight=cash / equity,
                fees=fees,
                impact_cost=impact_total,
                realized_pnl=sum(realized.values()),
                unrealized_pnl=sum(
                    shares[s] * (float(prices.loc[s, "close"]) - basis[s]) for s in symbols
                ),
                assets={
                    s: dict(
                        open=float(prices.loc[s, "open"]),
                        high=float(prices.loc[s, "high"]),
                        low=float(prices.loc[s, "low"]),
                        close=float(prices.loc[s, "close"]),
                        volume=float(prices.loc[s, "volume"]),
                        shares=shares[s],
                        market_value=shares[s] * float(prices.loc[s, "close"]),
                        weight=shares[s] * float(prices.loc[s, "close"]) / equity,
                        target_weight=targets[s],
                        realized_pnl=realized[s],
                        unrealized_pnl=shares[s] * (float(prices.loc[s, "close"]) - basis[s]),
                        fees=symbol_fees[s],
                        impact_cost=symbol_impact[s],
                        forecast=forecasts.get((day, s)),
                    )
                    for s in symbols
                },
            )
        )
        previous = day
        if progress:
            progress("跨日持仓与分批调仓", i + 1, len(days), "交易日")
    final = curve[-1]["equity"]
    liquidation_cost = sum(
        shares[s]
        * float(pivot[days[-1]].loc[s, "close"])
        * (costs.spread_bps / 2 + costs.slippage_bps + costs.sell_fee_bps)
        / 10000
        + max(costs.minimum_commission, shares[s] * costs.commission_per_share)
        for s in symbols
        if shares[s]
    )
    returns = (
        np.diff(np.r_[costs.initial_cash, [row["equity"] for row in curve]])
        / np.r_[
            costs.initial_cash,
            [row["equity"] for row in curve[:-1]],
        ]
    )
    return dict(
        config=config.model_dump(),
        start=start,
        end=end,
        allocation_decisions=allocation_decisions,
        portfolio_enabled=pooled_execution,
        engine_version=("daily-position-v3-daily" if daily_bars else "daily-position-v2")
        + ("-portfolio-v1" if config.allocation.enabled else "")
        + ("-rules-v1" if config.model in DAILY_RULE_MODELS else "")
        + ("-cost-aware-v1" if config.portfolio_policy == "cost_aware" else "")
        + (
            "-budget-v2"
            if config.capital_mode != "signal_budget" or config.entry_band is not None
            else ""
        ),
        metrics=dict(
            return_pct=(final / costs.initial_cash - 1) * 100,
            final_equity=final,
            max_drawdown_pct=max(row["drawdown_pct"] for row in curve),
            fees=fees,
            impact_cost=impact_total,
            trade_count=len(trades),
            halted=halted,
            turnover=turnover_total,
            realized_pnl=sum(realized.values()),
            unrealized_pnl=curve[-1]["unrealized_pnl"],
            trading_days=len(days),
            daily_sharpe=float(np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(252))
            if len(returns) > 1 and np.std(returns, ddof=1) > 1e-12
            else None,
            average_gross_exposure_pct=float(
                np.mean(
                    [row["gross_exposure"] for row in curve],
                )
                * 100
            ),
            estimated_liquidation_return_pct=((final - liquidation_cost) / costs.initial_cash - 1)
            * 100,
        ),
        curve=curve,
        trades=trades,
        signals=signals,
        positions=shares,
        contributions=[
            dict(
                symbol=s,
                net_profit=flows[s]
                + shares[s]
                * float(
                    pivot[days[-1]].loc[s, "close"],
                ),
            )
            for s in symbols
        ],
        daily_returns=[
            dict(date=d, return_pct=float(r * 100)) for d, r in zip(days, returns, strict=True)
        ],
        assumptions=[
            *(
                [
                    "组合分配仅调整原策略允许的股票；收缩协方差与成本惩罚、现金缓冲、先卖后买；常规成交受日换手预算限制，风险退出优先"
                ]
                if config.allocation.enabled
                else []
            ),
            "独立长期账户；仅做多无杠杆；持仓可隔夜，期末按收盘市值计价并保留未平仓头寸",
            (
                "供应商日线模拟；前日总成交量除以该日常规交易分钟数作为流动性估算，"
                "不是实际开盘或尾盘分钟成交量；供应商日线与常规时段分钟聚合可能存在口径差异"
                if daily_bars
                else "收盘信号在次日开盘执行；每日按固定资金比例分批调整，"
                "受前日最后一分钟成交量限制"
            ),
            "单股止损与组合回撤熔断优先；隔夜跳空可能穿透止损，熔断后本次回测不重启买入",
            "风险仅在开盘和收盘检查，非盘中实时止损；报告回撤为日终口径，可能低于盘中最大回撤",
            "当前为原始价格快照，未计股息；疑似拆股/极端跳变会拒绝回测，非总回报口径",
            "贝叶斯训练仅使用截至决策日已成熟的目标；历史日期已暴露，非全新样本外验证",
        ],
    )
