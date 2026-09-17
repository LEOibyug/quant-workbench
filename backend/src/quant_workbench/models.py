from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    strategy: Literal[
        "sma",
        "opening_breakout",
        "vwap_reversion",
        "adaptive",
        "trend_breakout",
        "range_reversion",
        "trend_pullback",
        "regime_adaptive",
        "adaptive_intraday",
    ] = "adaptive"
    fast: int = Field(default=5, ge=2, le=60)
    slow: int = Field(default=20, ge=3, le=120)
    flatten_minutes: int = Field(default=5, ge=1, le=30)
    opening_minutes: int = Field(default=15, ge=5, le=60)
    reversion_bps: float = Field(default=30, gt=0, le=500)
    stop_loss_bps: float = Field(default=100, gt=0, le=2000)
    regime_window: int = Field(default=60, ge=30, le=120)
    min_reward_risk: float = Field(default=1.2, ge=0.5, le=5)
    atr_window: int = Field(default=14, ge=5, le=60)
    stop_atr: float = Field(default=2, ge=0.5, le=5)
    take_atr: float = Field(default=3, ge=1, le=10)
    breakout_buffer_atr: float = Field(default=0.1, ge=0, le=1)
    reversion_atr: float = Field(default=2, ge=0.5, le=5)
    min_relative_volume: float = Field(default=1.2, ge=0.5, le=5)
    max_hold_minutes: int = Field(default=30, ge=5, le=120)
    cooldown_minutes: int = Field(default=10, ge=0, le=60)
    max_daily_entries: int = Field(default=4, ge=1, le=20)
    daily_loss_bps: float = Field(default=100, ge=10, le=1000)
    risk_per_trade_bps: float = Field(default=25, ge=1, le=100)
    rule_cost_multiplier: float = Field(default=1.5, ge=1, le=5)
    initial_cash: float = Field(default=100_000, ge=100, le=100_000_000)
    spread_bps: float = Field(default=2, ge=0, le=100)
    slippage_bps: float = Field(default=2, ge=0, le=100)
    commission_per_share: float = Field(default=0.005, ge=0, le=10)
    minimum_commission: float = Field(default=1, ge=0, le=100)
    sell_fee_bps: float = Field(default=0.3, ge=0, le=20)
    participation: float = Field(default=0.01, gt=0, le=0.1)

    @model_validator(mode="after")
    def window_order(self):
        if self.fast >= self.slow:
            raise ValueError("短均线窗口必须小于长均线窗口")
        return self


class ExperimentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(default="日内策略实验", min_length=1, max_length=80)
    dataset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    symbols: list[str] = Field(min_length=1, max_length=10)
    start: date
    train_end: date
    validation_end: date
    end: date
    config: StrategyConfig = Field(default_factory=StrategyConfig)
    model: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def dates(self):
        if not self.start < self.train_end < self.validation_end < self.end:
            raise ValueError("区间必须满足 开始 < 开发结束 < 验证结束 < 测试结束（右端不含）")
        self.symbols = sorted(set(s.strip().upper() for s in self.symbols))
        return self


class AlpacaInput(BaseModel):
    symbols: list[str] = Field(default=["NVDA", "TSLA", "AAPL"], min_length=1, max_length=10)
    start: date
    end: date
    feed: Literal["iex", "sip"] = "iex"


class ProviderInput(AlpacaInput):
    provider: Literal["alpaca", "massive"] = "alpaca"
