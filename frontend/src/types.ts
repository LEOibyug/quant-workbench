export type Phase = "train" | "validation" | "test";
export const phaseNames = {
  train: "开发",
  validation: "验证",
  test: "最终测试",
};
export const strategyNames: Record<string, string> = {
  trend_pullback: "趋势回调再入场",
  regime_adaptive: "趋势/震荡状态组合",
  adaptive_intraday: "局部均价回归 / 趋势恢复",
  trend_breakout: "趋势过滤突破 · ATR风控",
  range_reversion: "止跌确认回归 · ATR风控",
  adaptive: "按开发期特征匹配",
  sma: "双均线趋势",
  opening_breakout: "开盘区间突破",
  vwap_reversion: "VWAP偏离回归",
};
export interface Dataset {
  id: string;
  name: string;
  source: string;
  synthetic: boolean;
  rows: number;
  symbols: string[];
  dates: string[];
  start: string;
  end: string;
}
export interface Run {
  phase: Phase;
  status: string;
  error: string | null;
  progress?: import("./ProgressNotice").ProgressState;
}
export interface Profile {
  symbol: string;
  average_daily_volume: number;
  median_range_pct: number;
  intraday_volatility_bps: number;
  trend_efficiency: number;
  suggested_strategy: string;
  reason: string;
}
export interface Experiment {
  id: string;
  name: string;
  dataset_id: string;
  synthetic: boolean;
  source: string;
  start: string;
  train_end: string;
  validation_end: string;
  end: string;
  symbols: string[];
  runs: Run[];
  profiles: Profile[];
  strategies: Record<string, string>;
  config: {
    strategy: string;
    initial_cash: number;
    [key: string]: string | number;
  };
  model: { enabled: boolean };
  model_metadata?: Record<string, unknown>;
}
export interface Point {
  timestamp: string;
  equity: number;
  benchmark: number;
  drawdown_pct: number;
}
export interface Trade {
  timestamp: string;
  signal_time: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  impact_cost: number;
  reason: string;
}
export interface Result {
  phase: Phase;
  start: string;
  end: string;
  synthetic: boolean;
  source: string;
  metrics: Record<string, number | null>;
  curve: Point[];
  trades: Trade[];
  total_trades: number;
  curve_downsampled: boolean;
  assumptions: string[];
  prior_test_exposure: boolean;
  model_enabled?: boolean;
  rule_baseline?: Record<string, number | null>;
  contributions: { symbol: string; net_profit: number; strategy: string }[];
  model_statistics?: Record<string, unknown>;
  decision_funnel?: Record<string, unknown>;
}
