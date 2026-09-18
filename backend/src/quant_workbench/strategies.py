"""Causal intraday rules; risk thresholds frozen from the entry signal bar."""

from collections import deque

import numpy as np
import pandas as pd

from quant_workbench.costs import estimate_round_trip

REGIME_STRATEGIES = {"trend_pullback", "regime_adaptive", "adaptive_intraday"}
SCALING_STRATEGIES = {"scaled_reversion"}
REFINED_STRATEGIES = (
    {"trend_breakout", "range_reversion", "intraday_momentum"}
    | REGIME_STRATEGIES
    | SCALING_STRATEGIES
)
# 状态门控只约束均值回归类入场：趋势类本身自带方向条件。
REVERSION_GATE_STRATEGIES = {
    "vwap_reversion",
    "range_reversion",
    "regime_adaptive",
    "adaptive_intraday",
    "scaled_reversion",
}


def basket_regime_gate(frame, config):
    """Per-day entry admission from completed prior sessions only.

    Equal-weight basket of the dataset's symbols; the trailing window for a given
    day uses strictly earlier sessions, so future data cannot affect the gate.
    Days without enough prior history are denied (conservative). Returns {} when
    the gate is off, else {date_str: bool}.
    """
    if config.regime_gate == "off":
        return {}
    dates = frame.timestamp.dt.tz_convert("America/New_York").dt.date
    daily = (
        frame.assign(_d=dates)
        .sort_values("timestamp")
        .drop_duplicates(["_d", "symbol"], keep="last")
        .pivot(index="_d", columns="symbol", values="close")
        .sort_index()
    )
    index = (1 + daily.pct_change().mean(axis=1).fillna(0)).cumprod()
    window = config.regime_window_days
    ok = {}
    for i, day in enumerate(daily.index):
        if i < window:
            ok[str(day)] = False
            continue
        trailing = index.iloc[i - window : i + 1]
        drift_bps = float(trailing.iloc[-1] / trailing.iloc[0] - 1) * 10000
        path = float(trailing.diff().abs().sum())
        efficiency = (
            float(abs(trailing.iloc[-1] - trailing.iloc[0]) / path) if path > 0 else 0.0
        )
        gate = config.regime_gate
        ok[str(day)] = (
            (gate == "drift" and drift_bps >= config.regime_min_drift_bps)
            or (gate == "efficiency" and efficiency <= config.regime_max_efficiency)
            or (
                gate == "drift_and_efficiency"
                and drift_bps >= config.regime_min_drift_bps
                and efficiency <= config.regime_max_efficiency
            )
            or (
                gate == "drift_or_efficiency"
                and (
                    drift_bps >= config.regime_min_drift_bps
                    or efficiency <= config.regime_max_efficiency
                )
            )
        )
    return ok


class IntradayRules:
    def __init__(self, config, strategy, past=None):
        self.config, self.strategy = config, strategy
        self.daily_noise = deque(maxlen=20)
        if past is not None and len(past):
            day = past.timestamp.dt.tz_convert("America/New_York").dt.date
            for _, group in past.groupby(day, sort=True):
                self.daily_noise.append(float(((group.high - group.low) / group.close).mean()))
        self.reset(0)

    def reset(self, cash):
        if hasattr(self, "ranges") and self.ranges:
            self.daily_noise.append(float(np.mean(self.ranges)))
        self.bars = deque(
            maxlen=max(
                self.config.slow + 1,
                self.config.atr_window + 1,
                self.config.regime_window + 1 if self.strategy in REGIME_STRATEGIES else 0,
            )
        )
        self.ranges = []
        self.pv = self.volume = self.opening_high = 0.0
        self.count = self.entries = 0
        self.last_exit = -10000
        self.day_cash = cash
        self.day_halted = False
        self.entry_bar = None
        self.peak = self.stop_distance = self.take_distance = 0.0
        self.pending_distance = self.pending_take = 0.0
        self.max_quantity = None
        self.pending_mode = self.entry_mode = self.strategy
        self.entry_diagnostic = "等待规则观察"
        self.lots = []

    def filled(self, side, price, remaining, qty=None):
        if side == "buy":
            self.entries += 1
            self.entry_mode = self.pending_mode
            self.entry_bar = self.count + 1
            self.peak = price
            self.stop_distance = self.pending_distance
            self.take_distance = self.pending_take
            self.lots.append(
                dict(
                    qty=qty if qty is not None else remaining,
                    entry_bar=self.count + 1,
                    stop_price=price - self.pending_distance,
                    take_price=price + self.pending_take,
                )
            )
        elif remaining == 0:
            self.last_exit = self.count + 1
            self.entry_bar = None
            self.lots = []

    def lot_filled(self, index, qty):
        """部分或全部卖出第index批；该批清零时移除。"""
        lot = self.lots[index]
        lot["qty"] -= qty
        if lot["qty"] <= 0:
            self.lots.pop(index)
            if not self.lots:
                self.last_exit = self.count + 1

    def lot_exits(self, bar):
        """触发退出条件的批次：(下标, 数量, 原因)；各批独立目标/止损/时间退出。"""
        out = []
        for index, lot in enumerate(self.lots):
            if bar.close <= lot["stop_price"]:
                out.append((index, lot["qty"], "lot_stop"))
            elif bar.close >= lot["take_price"]:
                out.append((index, lot["qty"], "lot_take"))
            elif self.count - lot["entry_bar"] + 1 >= self.config.max_hold_minutes:
                out.append((index, lot["qty"], "lot_time"))
        return out

    def _scaled_signal(self, bar, shares, cash, close_time, vwap):
        """分批波动收割：偏离每加深一档加一批，各批独立回到均值目标。"""
        cfg = self.config
        if shares and self.day_halted:
            return False, "daily_loss_limit"
        self.entry_diagnostic = "风控/冷却/窗口/尾盘限制"
        if (
            self.day_halted
            or self.entries >= min(cfg.max_daily_entries, cfg.max_scaling_lots)
            or (not shares and self.count - self.last_exit <= cfg.cooldown_minutes)
            or len(self.bars) < max(cfg.slow + 1, cfg.atr_window + 1)
            or bar.timestamp
            >= close_time - pd.Timedelta(minutes=cfg.flatten_minutes + 1)
        ):
            return shares > 0, None
        bars = list(self.bars)
        true_range = [
            max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
            for a, b in zip(bars[:-1], bars[1:], strict=True)
        ]
        atr = float(np.mean(true_range[-cfg.atr_window :]))
        self.entry_diagnostic = "波动率不足"
        if atr <= 0:
            return shares > 0, None
        normal = float(np.mean(self.daily_noise)) if self.daily_noise else atr / bar.close
        self.entry_diagnostic = "波动率偏离历史范围"
        if not 0.5 * normal <= atr / bar.close <= 3 * normal:
            return shares > 0, None
        stop = min(cfg.stop_atr * atr, bar.close * cfg.stop_loss_bps / 10000)
        if stop <= 0:
            return shares > 0, None
        # 每批只占风险预算的1/批数；深档累计敞口仍受日损失限制与参与率约束。
        self.max_quantity = max(
            0,
            int(
                cash * (cfg.risk_per_trade_bps / cfg.max_scaling_lots) / 10000 / stop
            ),
        )
        cost = estimate_round_trip(bar.close, bar.volume, cash, cfg, self.max_quantity)
        cost_bps = cost["round_trip_bps"]
        self.entry_diagnostic = "资金或成交量不足"
        if cost_bps is None or self.max_quantity <= 0:
            return shares > 0, None
        band_bps = max(cfg.reversion_bps, cfg.reversion_atr * atr / bar.close * 10000)
        deviation_bps = (vwap - bar.close) / bar.close * 10000
        level = self.entries + 1
        target_distance = vwap - bar.close
        stabilized = bar.close >= bar.low + 0.25 * (bar.high - bar.low)
        signal = (
            deviation_bps >= level * band_bps
            and deviation_bps <= 6 * band_bps  # 过深偏离视为结构性下跌，不接飞刀
            and stabilized
        )
        self.entry_diagnostic = "目标空间不足以覆盖交易成本"
        signal = signal and target_distance / bar.close * 10000 > (
            cfg.rule_cost_multiplier * cost_bps + 1
        )
        if signal:
            self.entry_diagnostic = "规则入场候选"
            self.pending_distance = stop
            self.pending_take = min(target_distance, cfg.take_atr * atr)
            self.pending_mode = "scaled"
            return True, None
        self.entry_diagnostic = (
            "偏离未达下一档"
            if deviation_bps < level * band_bps
            else "偏离过深或未企稳"
        )
        return shares > 0, None

    def observe(self, bar, shares, entry_price, cash, close_time):
        cfg = self.config
        self.count += 1
        self.bars.append(bar)
        self.ranges.append((bar.high - bar.low) / bar.close)
        self.pv += (bar.high + bar.low + bar.close) / 3 * bar.volume
        self.volume += bar.volume
        vwap = self.pv / self.volume if self.volume else bar.close
        if self.count <= cfg.opening_minutes:
            self.opening_high = max(self.opening_high, bar.high)
        equity = cash + shares * bar.close
        if equity <= self.day_cash * (1 - cfg.daily_loss_bps / 10000):
            self.day_halted = True
        if self.strategy in SCALING_STRATEGIES:
            return self._scaled_signal(bar, shares, cash, close_time, vwap)
        if shares:
            self.peak = max(self.peak, bar.close)
            reason = None
            if self.day_halted:
                reason = "daily_loss_limit"
            elif bar.close <= entry_price - self.stop_distance:
                reason = "atr_stop"
            elif self.entry_mode != "momentum":
                # 尾盘动量持仓到收盘强制平仓，不做止盈/追踪/时间退出。
                if bar.close >= entry_price + self.take_distance:
                    reason = "atr_take_profit"
                elif self.peak >= entry_price + self.stop_distance and (
                    bar.close <= self.peak - self.stop_distance
                ):
                    reason = "atr_trailing"
                elif self.count - self.entry_bar + 1 >= cfg.max_hold_minutes:
                    reason = "time_exit"
                elif self.entry_mode in {"range_reversion", "range"} and bar.close >= vwap:
                    reason = "vwap_target"
                elif self.entry_mode in {"trend_breakout", "trend"} and bar.close < vwap:
                    reason = "trend_failed"
            return reason is None, reason
        self.max_quantity = None
        self.entry_diagnostic = "风控/冷却/窗口/尾盘限制"
        momentum_window = self.strategy == "intraday_momentum"
        guard_minutes = cfg.flatten_minutes + 1 if momentum_window else max(
            cfg.flatten_minutes + 1, cfg.max_hold_minutes
        )
        if (
            self.day_halted
            or self.entries >= cfg.max_daily_entries
            or self.count - self.last_exit <= cfg.cooldown_minutes
            or len(self.bars) < max(cfg.slow + 1, cfg.atr_window + 1)
            or bar.timestamp >= close_time - pd.Timedelta(minutes=guard_minutes)
        ):
            return False, None
        bars = list(self.bars)
        close = np.array([b.close for b in bars])
        true_range = np.array(
            [
                max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                for a, b in zip(bars[:-1], bars[1:], strict=True)
            ]
        )
        atr = float(true_range[-cfg.atr_window :].mean())
        self.entry_diagnostic = "波动率不足"
        if atr <= 0:
            return False, None
        # Historical volatility regime is based on completed prior sessions only.
        normal = float(np.mean(self.daily_noise)) if self.daily_noise else atr / bar.close
        self.entry_diagnostic = "波动率偏离历史范围"
        if not 0.5 * normal <= atr / bar.close <= 3 * normal:
            return False, None
        stop = min(cfg.stop_atr * atr, bar.close * cfg.stop_loss_bps / 10000)
        self.max_quantity = max(0, int(cash * cfg.risk_per_trade_bps / 10000 / stop))
        cost = estimate_round_trip(bar.close, bar.volume, cash, cfg, self.max_quantity)
        cost_bps = cost["round_trip_bps"]
        self.entry_diagnostic = "资金或成交量不足"
        if cost_bps is None:
            return False, None
        efficiency = abs(close[-1] - close[-cfg.slow]) / max(
            np.abs(np.diff(close[-cfg.slow :])).sum(), 1e-12
        )
        fast, slow = close[-cfg.fast :].mean(), close[-cfg.slow :].mean()
        relative_volume = bar.volume / max(np.mean([b.volume for b in bars[:-1]]), 1)
        self.entry_diagnostic = "形态条件未满足"
        if self.strategy in REGIME_STRATEGIES:
            signal, target_distance, mode = self.regime_signal(bars, close, atr, vwap)
            self.pending_mode = mode
            signal = signal and min(target_distance, cfg.take_atr * atr) >= (
                cfg.min_reward_risk * stop
            )
        elif self.strategy == "intraday_momentum":
            # Gao-Han-Li-Zhou (2018): 当日已实现动量延续到尾盘；仅尾盘窗口入场，持有到收盘。
            day_open = bars[0].open
            momentum_bps = (bar.close / day_open - 1) * 10000
            self.pending_mode = "momentum"
            target_distance = cfg.take_atr * atr
            in_window = bar.timestamp >= close_time - pd.Timedelta(minutes=30)
            signal = in_window and momentum_bps >= cfg.momentum_threshold_bps
        elif self.strategy == "trend_breakout":
            barrier = max(self.opening_high, max(b.high for b in bars[-cfg.slow : -1]))
            target_distance = cfg.take_atr * atr
            signal = (
                self.count > cfg.opening_minutes
                and close[-2] <= barrier
                and bar.close > barrier + cfg.breakout_buffer_atr * atr
                and bar.close > vwap
                and fast > slow
                and efficiency >= 0.25
                and relative_volume >= cfg.min_relative_volume
                and bar.close - vwap <= 4 * atr
            )
        else:
            target_distance = vwap - bar.close
            signal = (
                efficiency <= 0.35
                and target_distance
                >= max(cfg.reversion_bps / 10000 * bar.close, cfg.reversion_atr * atr)
                and bar.close > close[-2]
                and bar.close > bar.open
                and bar.close >= bar.low + 0.6 * (bar.high - bar.low)
            )
        if signal:
            self.entry_diagnostic = "目标空间不足以覆盖交易成本"
        # This is opportunity distance, not a forecast of expected profit.
        signal = signal and min(target_distance, cfg.take_atr * atr) / bar.close * 10000 > (
            cfg.rule_cost_multiplier * cost_bps + 1
        )
        if signal:
            self.entry_diagnostic = "规则入场候选"
            self.pending_distance = stop
            self.pending_take = min(target_distance, cfg.take_atr * atr)
        return bool(signal), None

    def regime_signal(self, bars, close, atr, vwap):
        cfg, bar = self.config, bars[-1]
        if len(close) < cfg.regime_window + 1:
            return False, 0, "flat"
        slow = close[-cfg.slow :].mean()
        fast = close[-cfg.fast :].mean()
        previous_fast = close[-cfg.fast - 1 : -1].mean()
        width = cfg.regime_window // 3
        slope = (
            close[-width:].mean() - close[-cfg.regime_window : -cfg.regime_window + width].mean()
        ) / atr
        efficiency = abs(close[-1] - close[-cfg.regime_window]) / max(
            np.abs(np.diff(close[-cfg.regime_window :])).sum(), 1e-12
        )
        if self.strategy == "adaptive_intraday":
            # Local fair value responds to intraday shifts; never assume the opening VWAP
            # remains a reachable target after a persistent selloff.
            local = bars[-cfg.slow :]
            weights = np.array([b.volume for b in local], dtype=float)
            typical = np.array([(b.high + b.low + b.close) / 3 for b in local])
            fair = float(np.average(typical, weights=weights)) if weights.sum() else slow
            recovering = bar.close > close[-2] and bar.close > bar.open
            if slope >= 0.5 and fast > slow and bar.close > vwap:
                touched = min(b.low for b in bars[-5:-1]) <= previous_fast + 0.5 * atr
                return (
                    bool(
                        touched
                        and recovering
                        and bar.close > fast
                        and bar.close - fast <= 1.5 * atr
                    ),
                    cfg.take_atr * atr,
                    "trend",
                )
            # Block strong downtrends; require recovery and a real local mean-reversion gap.
            gap = fair - bar.close
            deviation = max(cfg.reversion_bps * bar.close / 10000, cfg.reversion_atr * atr)
            signal = (
                slope > -2
                and efficiency < 0.45
                and gap >= deviation
                and recovering
                and bar.close >= bar.low + 0.5 * (bar.high - bar.low)
            )
            return bool(signal), gap, "local_range"
        if slope >= 1 and bar.close > vwap and fast > slow:
            touched = min(b.low for b in bars[-6:-1]) <= previous_fast + 0.25 * atr
            recovering = bar.close > bars[-2].high and bar.close > fast
            not_extended = bar.close - slow <= 2 * atr and bar.close - vwap <= 3 * atr
            return bool(touched and recovering and not_extended), cfg.take_atr * atr, "trend"
        if self.strategy == "regime_adaptive" and abs(slope) <= 1 and efficiency <= 0.25:
            deviation = max(
                cfg.reversion_bps * bar.close / 10000,
                cfg.reversion_atr * atr,
                1.5 * close[-cfg.regime_window :].std(),
            )
            recovering = (
                bar.close > bars[-2].close
                and bar.low > bars[-2].low
                and bar.close > bar.open
                and bar.close >= bar.low + 0.6 * (bar.high - bar.low)
            )
            return bool(vwap - bar.close >= deviation and recovering), vwap - bar.close, "range"
        return False, 0, "flat"
