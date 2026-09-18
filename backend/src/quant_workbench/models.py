from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_workbench.allocation import AllocationConfig


class StrategyConfig(BaseModel):
    allocation: AllocationConfig = Field(default_factory=AllocationConfig)
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
        "intraday_momentum",
        "scaled_reversion",
        "ou_reversion",
        "ou_scaling",
        "kalman_trend",
        "bayesian_session",
    ] = "adaptive"
    fast: int = Field(default=5, ge=2, le=60)
    stat_window: int = Field(default=120, ge=30, le=390)
    stat_horizon: int = Field(default=15, ge=5, le=60)
    stat_entry_z: float = Field(default=1.5, ge=0.5, le=4)
    stat_confidence: float = Field(default=0.5, ge=0, le=3)
    stat_process_noise: float = Field(default=0.001, ge=0.00001, le=0.1)
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
    momentum_threshold_bps: float = Field(default=10, ge=-100, le=500)
    # 因果市场状态门控：只允许用已完成的历史交易日判断当日是否入场。
    regime_gate: Literal[
        "off", "drift", "efficiency", "drift_and_efficiency", "drift_or_efficiency"
    ] = "off"
    regime_window_days: int = Field(default=10, ge=2, le=60)
    regime_min_drift_bps: float = Field(default=0, ge=-1000, le=5000)
    regime_max_efficiency: float = Field(default=0.35, ge=0.05, le=1)
    # 分批波动收割：偏离加深逐档加仓，各批独立目标/止损。
    max_scaling_lots: int = Field(default=3, ge=1, le=5)
    # 盈亏平衡持有：低于成交价+成本时耐心窗口内不卖，趋势转弱才认赔；灾难止损仍生效。
    lot_breakeven_hold: bool = False
    lot_patience_minutes: int = Field(default=45, ge=5, le=240)
    lot_hard_stop_atr: float = Field(default=4, ge=1, le=10)
    # 新增批次要求日内看涨趋势（上涨趋势中买回调，不逆势加仓）。
    tranche_requires_uptrend: bool = False
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
    symbols: list[str] = Field(min_length=1, max_length=20)
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
    symbols: list[str] = Field(default=["NVDA", "TSLA", "AAPL"], min_length=1, max_length=20)
    start: date
    end: date
    feed: Literal["iex", "sip"] = "iex"


class ProviderInput(AlpacaInput):
    provider: Literal["alpaca", "massive"] = "alpaca"
