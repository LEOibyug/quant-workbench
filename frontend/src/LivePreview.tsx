import { strategyNames } from "./types";

interface LiveStrategy {
  name: string;
  version: string;
  horizon_type?: "short" | "long";
  symbols: string[];
  strategies: Record<string, string>;
  strategy_config: { initial_cash: number };
  position_config?: {
    model: string;
    rebalance_days: number;
    tranche_weight: number;
    costs: { initial_cash: number };
  };
}

export function LivePreview({ deployment: d, onBack }: {
  deployment: LiveStrategy; onBack: () => void;
}) {
  const long = d.horizon_type === "long";
  const cash = long ? d.position_config?.costs.initial_cash : d.strategy_config.initial_cash;
  return <>
    <div className="page-title">
      <div><div className="eyebrow">LIVE / STRATEGY DEPLOYMENT</div>
        <h1>Live 策略部署</h1>
        <p>管理交易账户、策略部署与持仓订单。</p>
      </div>
      <button type="button" className="secondary" onClick={onBack}>返回策略展示</button>
    </div>
    <div className="metric-grid">
      <div className="card metric"><span>账户连接</span><strong>未连接</strong></div>
      <div className="card metric"><span>策略状态</span><strong>未启动</strong></div>
      <div className="card metric"><span>账户净值</span><strong>—</strong></div>
      <div className="card metric"><span>今日盈亏</span><strong>—</strong></div>
    </div>
    <section className="card">
      <h2>待应用策略</h2>
      <h3>{d.name}</h3>
      <p>版本 {d.version} · {long ? "长期 · 日线与隔夜持仓" : "短期 · 日内交易"}</p>
      <div className="live-summary">
        <p><span className="muted">策略参考资金（非账户余额）</span><br />
          <strong>{cash == null ? "—" : new Intl.NumberFormat("zh-CN", { style: "currency", currency: "USD" }).format(cash)}</strong></p>
        <p><span className="muted">支持股票</span><br /><strong>{d.symbols.length} 支</strong></p>
        {long && d.position_config && <p><span className="muted">执行设置</span><br />
          每 {d.position_config.rebalance_days} 个交易日更新目标 · 每日单股最多调整 {(d.position_config.tranche_weight * 100).toFixed(1)}%</p>}
      </div>
      <p className="muted">以下为已发布版本的支持范围，不代表实际持仓或已提交订单。</p>
      <div className="table-wrap"><table><thead><tr><th>股票</th><th>策略</th><th>状态</th></tr></thead>
        <tbody>{d.symbols.map(s => <tr key={s}><td>{s}</td>
          <td>{strategyNames[d.strategies[s]] || d.strategies[s] || "—"}</td><td>待应用</td></tr>)}</tbody>
      </table></div>
    </section>
    <section className="card">
      <h2>交易账户</h2>
      <p>尚未接入券商账户。账户资金、持仓和订单将在接入后展示。</p>
      <div className="live-entry"><button type="button" disabled>连接账户</button>
        <button type="button" disabled>启动策略</button></div>
    </section>
    <section className="card"><h2>持仓与订单</h2>
      <p className="muted">连接账户后查看持仓与订单。</p>
    </section>
  </>;
}
