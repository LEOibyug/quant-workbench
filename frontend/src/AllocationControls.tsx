import { useState } from "react";

export interface AllocationConfig {
  enabled: boolean; symbols: string[]; lookback: number; max_positions: number;
  max_weight: number; cash_reserve: number; risk_aversion: number; cost_penalty: number;
  rebalance_band: number; max_daily_turnover: number; rebalance_minutes: number;
}
export function readAllocation(form: FormData): AllocationConfig {
  const n = (key: string) => Number(form.get(`allocation_${key}`));
  return {
    enabled: form.get("allocation_enabled") === "on",
    symbols: form.getAll("allocation_symbols").map(String),
    lookback: n("lookback"), max_positions: n("max_positions"),
    max_weight: n("max_weight") / 100, cash_reserve: n("cash_reserve") / 100,
    risk_aversion: n("risk_aversion"), cost_penalty: n("cost_penalty"),
    rebalance_band: n("rebalance_band") / 100,
    max_daily_turnover: n("max_daily_turnover") / 100,
    rebalance_minutes: n("rebalance_minutes"),
  };
}
export function AllocationControls({ symbols, initial, long = false }: {
  symbols: string[]; initial?: AllocationConfig; long?: boolean;
}) {
  const [enabled, setEnabled] = useState(initial?.enabled || false);
  const fields: [keyof AllocationConfig, string, number, number, number, number][] = [
    ["lookback", `风险窗口 ${long ? "交易日" : "分钟"}`, 60, 20, 252, 1],
    ["max_positions", "轮换池目标持有数", 3, 1, 10, 1],
    ["max_weight", "组合单股上限 %", 35, 1, 50, 1],
    ["cash_reserve", "目标现金缓冲 %", 5, 0, 90, 1],
    ["risk_aversion", "风险惩罚系数", 10, 0.1, 100, 0.1],
    ["cost_penalty", "换仓成本惩罚倍数", 2, 0, 10, 0.1],
    ["rebalance_band", "最小调仓差额 / 净值 %", 2, 0, 20, 0.1],
    ["max_daily_turnover", "每日常规成交总额 / 净值 %", long ? 20 : 100, 1, 1000, 1],
    ["rebalance_minutes", "日内分配间隔 分钟", 30, 5, 120, 1],
  ];
  return <section className="allocation-controls">
    <h3>组合资金分配与轮换</h3>
    <label className="inline"><input name="allocation_enabled" type="checkbox" checked={enabled}
      onChange={(e) => setEnabled(e.target.checked)} />启用共享资金与风险成本分配</label>
    <p className="muted">与原策略共同作用：先筛选可交易股票，再按风险、相关性和换仓成本分配资金。
      启用股票使用组合单股上限；止损与清仓优先，不保证满仓或盈利。</p>
    <div hidden={!enabled}>
      <div className="checks">{symbols.map((symbol) => <label key={symbol}>
        <input type="checkbox" name="allocation_symbols" value={symbol}
          defaultChecked={!initial?.symbols.length || initial.symbols.includes(symbol)} />{symbol}
      </label>)}</div>
      <p className="muted">此处仅选择资金轮换参与范围，不是交易开关：取消勾选仍可能按原策略买卖。要排除股票，请在实验 / 模拟的交易股票选择中取消。全部不勾选表示全部参与。
        {long ? "按上方交易日调仓间隔重新分配。" : "同一分钟先卖后买；尾盘清仓，不隔夜。"}</p>
    </div>
    <div className="form-grid" hidden={!enabled}>
      {fields.map(([key, label, fallback, min, max, step]) => {
        const percent = ["max_weight", "cash_reserve", "rebalance_band", "max_daily_turnover"].includes(key);
        const value = initial?.[key];
        return <label key={key} hidden={long && key === "rebalance_minutes"}>{label}
          <input name={`allocation_${key}`} type="number" min={min} max={max} step={step}
            defaultValue={typeof value === "number" ? value * (percent ? 100 : 1) : fallback} required />
        </label>;
      })}
    </div>
  </section>;
}
