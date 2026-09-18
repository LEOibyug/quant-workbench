"""Independent daily-position engine: overnight holdings and staged target-weight execution."""

import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from sklearn.linear_model import BayesianRidge
from sklearn.preprocessing import StandardScaler

from quant_workbench.market_data import require_complete
from quant_workbench.models import StrategyConfig


class PositionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    model: Literal["trend", "bayesian", "equal_weight"] = "bayesian"
    lookback: int = Field(default=20, ge=10, le=60)
    horizon: int = Field(default=5, ge=1, le=20)
    rebalance_days: int = Field(default=5, ge=1, le=20)
    confidence: float = Field(default=0.5, ge=0, le=3)
    tranche_weight: float = Field(default=0.05, gt=0, le=0.2)
    max_weight: float = Field(default=0.2, gt=0, le=0.5)
    daily_vol_target: float = Field(default=0.015, gt=0, le=0.05)
    stop_loss_pct: float = Field(default=10, ge=2, le=30)
    max_drawdown_pct: float = Field(default=10, ge=2, le=30)
    costs: StrategyConfig = Field(default_factory=StrategyConfig)


def daily_inputs(frame):
    frame = frame.sort_values(["symbol", "timestamp"])
    day = frame.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    daily = frame.assign(day=day).groupby(["day", "symbol"], as_index=False).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), last_volume=("volume", "last"),
    )
    for _, group in daily.groupby("symbol"):
        gap = group.open.to_numpy()[1:] / group.close.to_numpy()[:-1]
        if np.any((gap < 0.65) | (gap > 1.5)):
            raise ValueError("检测到疑似拆股或极端隔夜跳变；跨日回测需先核验公司行动数据")
    return daily


def daily_forecasts(daily, config):
    """Each forecast fits only labels whose target day has already closed."""
    symbols = sorted(daily.symbol.unique())
    days = sorted(daily.day.unique())
    rows = []
    for symbol, group in daily.groupby("symbol"):
        group = group.sort_values("day").reset_index(drop=True)
        close = group.close.to_numpy()
        for i in range(config.lookback, len(group)):
            returns = np.diff(np.log(close[i-config.lookback:i+1]))
            volatility = max(float(returns.std()), 1e-6)
            features = [
                math.log(close[i] / close[i-5]), float(returns.sum()), volatility,
                close[i] / close[i-config.lookback:i+1].mean() - 1,
                *[float(symbol == s) for s in symbols],
            ]
            target_index = i + config.horizon
            target_day = group.iloc[target_index].day if target_index < len(group) else None
            target = (math.log(close[target_index] / group.iloc[i+1].open) * 10000
                      if target_day is not None else None)
            rows.append(dict(
                day=group.iloc[i].day, symbol=symbol, x=features, y=target,
                target_day=target_day, volatility=volatility,
                mean=float(returns.mean()) * config.horizon * 10000,
                uncertainty=volatility * math.sqrt(config.horizon) * 10000,
            ))
    output = {}
    for i, day in enumerate(days):
        today = [row for row in rows if row["day"] == day]
        if not today:
            continue
        if config.model == "bayesian":
            lower = days[max(0, i-60)]
            train = [row for row in rows if row["target_day"] is not None
                     and row["target_day"] <= day and row["day"] >= lower]
            if len(train) < 50:
                continue
            scaler = StandardScaler()
            model = BayesianRidge().fit(
                scaler.fit_transform([row["x"] for row in train]), [row["y"] for row in train],
            )
            means, uncertainties = model.predict(
                scaler.transform([row["x"] for row in today]), return_std=True,
            )
            last_target = max(row["target_day"] for row in train)
        else:
            means = [row["mean"] for row in today]
            uncertainties = [row["uncertainty"] for row in today]
            last_target = None
        for row, mean, uncertainty in zip(today, means, uncertainties, strict=True):
            output[(day, row["symbol"])] = dict(
                mean_bps=float(mean), uncertainty_bps=float(uncertainty),
                volatility=row["volatility"], last_training_target=last_target,
            )
    return output


def simulate_positions(frame, config, start, end, progress=None):
    require_complete(frame, start, end)
    # Do not let post-evaluation observations enter this experiment at all.
    cutoff = pd.Timestamp(end, tz="America/New_York").tz_convert("UTC")
    daily = daily_inputs(frame[frame.timestamp < cutoff])
    forecasts = daily_forecasts(daily, config) if config.model != "equal_weight" else {}
    symbols = sorted(daily.symbol.unique())
    pivot = {day: group.set_index("symbol") for day, group in daily.groupby("day")}
    days = sorted(day for day in pivot if start <= day < end)
    costs = config.costs
    cash = peak = costs.initial_cash
    shares = {s: 0 for s in symbols}
    basis = {s: 0.0 for s in symbols}
    flows = {s: 0.0 for s in symbols}
    targets = {s: 0.0 for s in symbols}
    target_shares = {s: 0 for s in symbols}
    forced_exit = {s: False for s in symbols}
    halted = False
    trades, curve, signals = [], [], []
    fees = impact_total = 0.0
    previous = None
    for i, day in enumerate(days):
        prices = pivot[day]
        if previous is not None:
            opening_equity = cash + sum(
                shares[s] * float(prices.loc[s, "open"]) for s in symbols
            )
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
                if quantity:
                    orders.append((delta > 0, symbol, quantity))
            for buying, symbol, quantity in sorted(orders):
                raw = float(prices.loc[symbol, "open"])
                impact = raw * (costs.spread_bps / 2 + costs.slippage_bps) / 10000
                price = raw + impact if buying else raw - impact
                if buying:
                    quantity = min(quantity, max(0, math.floor(cash / price)))
                    while quantity and quantity * price + max(
                        costs.minimum_commission, quantity * costs.commission_per_share,
                    ) > cash:
                        quantity -= 1
                if not quantity:
                    continue
                fee = max(costs.minimum_commission, quantity * costs.commission_per_share)
                fee += 0 if buying else quantity * price * costs.sell_fee_bps / 10000
                if buying:
                    basis[symbol] = (
                        basis[symbol] * shares[symbol] + quantity * price + fee
                    ) / (shares[symbol] + quantity)
                    shares[symbol] += quantity
                    cash -= quantity * price + fee
                    flows[symbol] -= quantity * price + fee
                else:
                    shares[symbol] -= quantity
                    cash += quantity * price - fee
                    flows[symbol] += quantity * price - fee
                    if not shares[symbol]:
                        basis[symbol] = 0.0
                fees += fee
                impact_total += quantity * impact
                trades.append(dict(
                    date=day, signal_date=previous, symbol=symbol,
                    side="buy" if buying else "sell", quantity=quantity, price=price, fee=fee,
                    position_after=shares[symbol],
                    reason="risk_exit" if halted or forced_exit[symbol] else "staged_rebalance",
                ))
        equity = cash + sum(shares[s] * float(prices.loc[s, "close"]) for s in symbols)
        peak = max(peak, equity)
        halted = halted or equity <= peak * (1 - config.max_drawdown_pct / 100)
        if i % config.rebalance_days == 0:
            for symbol in symbols:
                forecast = forecasts.get((day, symbol))
                close = float(prices.loc[symbol, "close"])
                quantity = max(1, math.floor(equity * config.tranche_weight / close))
                cost_bps = 2 * (costs.spread_bps / 2 + costs.slippage_bps) + costs.sell_fee_bps
                cost_bps += 2 * max(
                    costs.minimum_commission, quantity * costs.commission_per_share,
                ) / (quantity * close) * 10000
                edge = (forecast["mean_bps"] - config.confidence * forecast["uncertainty_bps"]
                        if forecast else -math.inf)
                weight = min(config.max_weight, 1 / len(symbols)) * min(
                    1, config.daily_vol_target / forecast["volatility"],
                ) if forecast and edge > 1.5 * cost_bps else 0.0
                if config.model == "equal_weight":
                    weight = min(config.max_weight, 1 / len(symbols))
                targets[symbol] = weight
                target_shares[symbol] = math.floor(equity * weight / close)
                signals.append(dict(date=day, symbol=symbol, target_weight=weight,
                                    forecast=forecast))
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
        curve.append(dict(
            date=day, equity=equity, cash=cash, drawdown_pct=(1-equity/peak)*100,
            gross_exposure=(equity-cash)/equity, halted=halted, positions=dict(shares),
        ))
        previous = day
        if progress:
            progress("跨日持仓与分批调仓", i+1, len(days), "交易日")
    final = curve[-1]["equity"]
    liquidation_cost = sum(
        shares[s] * float(pivot[days[-1]].loc[s, "close"]) * (
            costs.spread_bps / 2 + costs.slippage_bps + costs.sell_fee_bps
        ) / 10000 + max(costs.minimum_commission, shares[s] * costs.commission_per_share)
        for s in symbols if shares[s]
    )
    returns = np.diff(np.r_[costs.initial_cash, [row["equity"] for row in curve]]) / np.r_[
        costs.initial_cash, [row["equity"] for row in curve[:-1]],
    ]
    return dict(
        config=config.model_dump(), start=start, end=end, engine_version="daily-position-v2",
        metrics=dict(return_pct=(final/costs.initial_cash-1)*100, final_equity=final,
                     max_drawdown_pct=max(row["drawdown_pct"] for row in curve),
                     fees=fees, impact_cost=impact_total, trade_count=len(trades), halted=halted,
                     average_gross_exposure_pct=float(np.mean(
                         [row["gross_exposure"] for row in curve],
                     ) * 100),
                     estimated_liquidation_return_pct=(
                         (final-liquidation_cost)/costs.initial_cash-1
                     )*100),
        curve=curve, trades=trades, signals=signals, positions=shares,
        contributions=[dict(symbol=s, net_profit=flows[s] + shares[s] * float(
            pivot[days[-1]].loc[s, "close"],
        )) for s in symbols],
        daily_returns=[dict(date=d, return_pct=float(r*100))
                       for d, r in zip(days, returns, strict=True)],
        assumptions=["独立长期账户；仅做多无杠杆；持仓可隔夜，期末按收盘市值计价并保留未平仓头寸",
                     "收盘信号在次日开盘执行；每日按固定资金比例分批调整，受前日最后一分钟成交量限制",
                     "单股止损与组合回撤熔断优先；隔夜跳空可能穿透止损，熔断后本次回测不重启买入",
                     "风险仅在开盘和收盘检查，非盘中实时止损；报告回撤为日终口径，可能低于盘中最大回撤",
                     "当前为原始价格快照，未计股息；疑似拆股/极端跳变会拒绝回测，非总回报口径",
                     "贝叶斯训练仅使用截至决策日已成熟的目标；历史日期已暴露，非全新样本外验证"],
    )
