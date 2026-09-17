"""Causal intraday rules; risk thresholds frozen from the entry signal bar."""

from collections import deque

import numpy as np
import pandas as pd

from quant_workbench.costs import estimate_round_trip

REGIME_STRATEGIES = {"trend_pullback", "regime_adaptive"}
REFINED_STRATEGIES = {"trend_breakout", "range_reversion"} | REGIME_STRATEGIES


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

    def filled(self, side, price, remaining):
        if side == "buy":
            self.entries += 1
            self.entry_mode = self.pending_mode
            self.entry_bar = self.count + 1
            self.peak = price
            self.stop_distance = self.pending_distance
            self.take_distance = self.pending_take
        elif remaining == 0:
            self.last_exit = self.count + 1
            self.entry_bar = None

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
        if shares:
            self.peak = max(self.peak, bar.close)
            reason = None
            if self.day_halted:
                reason = "daily_loss_limit"
            elif bar.close <= entry_price - self.stop_distance:
                reason = "atr_stop"
            elif bar.close >= entry_price + self.take_distance:
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
        if (
            self.day_halted
            or self.entries >= cfg.max_daily_entries
            or self.count - self.last_exit <= cfg.cooldown_minutes
            or len(self.bars) < max(cfg.slow + 1, cfg.atr_window + 1)
            or bar.timestamp
            >= close_time - pd.Timedelta(minutes=max(cfg.flatten_minutes + 1, cfg.max_hold_minutes))
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
        if atr <= 0:
            return False, None
        # Historical volatility regime is based on completed prior sessions only.
        normal = float(np.mean(self.daily_noise)) if self.daily_noise else atr / bar.close
        if not 0.5 * normal <= atr / bar.close <= 3 * normal:
            return False, None
        stop = min(cfg.stop_atr * atr, bar.close * cfg.stop_loss_bps / 10000)
        self.max_quantity = max(0, int(cash * cfg.risk_per_trade_bps / 10000 / stop))
        cost = estimate_round_trip(bar.close, bar.volume, cash, cfg, self.max_quantity)
        cost_bps = cost["round_trip_bps"]
        if cost_bps is None:
            return False, None
        efficiency = abs(close[-1] - close[-cfg.slow]) / max(
            np.abs(np.diff(close[-cfg.slow :])).sum(), 1e-12
        )
        fast, slow = close[-cfg.fast :].mean(), close[-cfg.slow :].mean()
        relative_volume = bar.volume / max(np.mean([b.volume for b in bars[:-1]]), 1)
        if self.strategy in REGIME_STRATEGIES:
            signal, target_distance, mode = self.regime_signal(bars, close, atr, vwap)
            self.pending_mode = mode
            signal = signal and min(target_distance, cfg.take_atr * atr) >= (
                cfg.min_reward_risk * stop
            )
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
        # This is opportunity distance, not a forecast of expected profit.
        signal = signal and min(target_distance, cfg.take_atr * atr) / bar.close * 10000 > (
            cfg.rule_cost_multiplier * cost_bps + 1
        )
        if signal:
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
