import { useEffect, useState } from "react";
import { post } from "./api";
import { DownloadButton, observeOperation, ProgressNotice, type ProgressState } from "./ProgressNotice";
import type { Dataset } from "./types";

interface PositionResult {
  start: string;
  end: string;
  config: { model: string; lookback: number; horizon: number; rebalance_days: number; tranche_weight: number };
  metrics: { return_pct: number; max_drawdown_pct: number; trade_count: number; halted: boolean };
  curve: { date: string; equity: number; gross_exposure: number }[];
  trades: { date: string; symbol: string; side: string; quantity: number; price: number; position_after: number; reason: string }[];
  positions: Record<string, number>;
  assumptions: string[];
}
const pendingKey = "quant.pending.position.operation";
const lastKey = "quant.last.position.operation";

export function PositionPanel({ datasets }: { datasets: Dataset[] }) {
  const [datasetId, setDatasetId] = useState("");
  const dataset = datasets.find((d) => d.id === datasetId) || datasets[0];
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const [result, setResult] = useState<PositionResult | null>(null);
  const [jobId, setJobId] = useState("");
  const [error, setError] = useState("");
  async function observe(id: string) {
    setBusy(true); setError(""); setJobId(id);
    try {
      setResult(await observeOperation<PositionResult>(id, (value) => {
        setProgress(value);
        if (["completed", "failed"].includes(value.status)) localStorage.removeItem(pendingKey);
      }));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    const saved = localStorage.getItem(pendingKey) || localStorage.getItem(lastKey);
    if (saved) void observe(saved);
  }, []);
  async function launch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dataset || busy) return;
    if (localStorage.getItem(pendingKey)) {
      setError("先恢复尚未确认完成的长期任务"); return;
    }
    const f = new FormData(event.currentTarget);
    const n = (key: string) => Number(f.get(key));
    setBusy(true); setError(""); setResult(null);
    try {
      const job = await post<{ id: string }>("/position/run", {
        dataset_id: dataset.id, symbols: dataset.symbols,
        start: f.get("start"), end: f.get("end"),
        config: {
          model: f.get("model"), lookback: n("lookback"), horizon: n("horizon"),
          rebalance_days: n("rebalance"), confidence: n("confidence"),
          tranche_weight: n("tranche") / 100,
          costs: { initial_cash: n("cash") },
        },
      });
      localStorage.setItem(pendingKey, job.id);
      localStorage.setItem(lastKey, job.id);
      await observe(job.id);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }
  const min = result ? Math.min(...result.curve.map((p) => p.equity)) : 0;
  const max = result ? Math.max(...result.curve.map((p) => p.equity)) : 1;
  return <section className="card">
    <h2>长期低频 · 隔夜持仓与分批调仓</h2>
    <p>独立日线模型，持仓数日至数周；收盘形成目标仓位，次日开盘分批执行。
      与短期策略分别核算资金，研究结果不会提交真实订单。</p>
    {error && <p className="notice error" role="alert">{error}</p>}
    <ProgressNotice value={progress} />
    {!busy && localStorage.getItem(pendingKey) && <button onClick={() => void observe(localStorage.getItem(pendingKey)!)}>恢复长期任务</button>}
    <label>行情数据集<select value={dataset?.id || ""} disabled={busy} onChange={(e) => setDatasetId(e.target.value)}>
      {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
    </select></label>
    {dataset && <form key={dataset.id} onSubmit={launch}>
      <div className="form-grid">
        <label>长期模型<select name="model" defaultValue="" required>
          <option value="" disabled>选择长期模型</option>
          <option value="trend">统计趋势 + 波动率仓位</option>
          <option value="bayesian">贝叶斯多日收益回归</option>
          <option value="equal_weight">等权再平衡对照</option>
        </select></label>
        <label>开始日期<input name="start" type="date" required defaultValue={dataset.start} /></label>
        <label>结束日期（不含）<input name="end" type="date" required defaultValue={new Date(Date.parse(dataset.end) + 86400000).toISOString().slice(0, 10)} /></label>
        <label>独立资金 USD<input name="cash" type="number" min={100} defaultValue={100000} required /></label>
        <label>历史窗口 交易日<input name="lookback" type="number" min={10} max={60} defaultValue={20} required /></label>
        <label>预测跨度 交易日<input name="horizon" type="number" min={1} max={20} defaultValue={5} required /></label>
        <label>调仓间隔 交易日<input name="rebalance" type="number" min={1} max={20} defaultValue={5} required /></label>
        <label>不确定性扣减倍数<input name="confidence" type="number" min={0} max={3} step={0.1} defaultValue={0.5} required /></label>
        <label>每日单股最大调整 资金%<input name="tranche" type="number" min={0.1} max={20} step={0.1} defaultValue={5} required /></label>
      </div>
      <p className="muted">{dataset.symbols.join(" / ")}。默认单股目标上限20%、止损10%、组合回撤10%后熔断。
        价差2bps、滑点2bps，佣金每股$0.005、每次最低$1。模型历史不足时持币；已有数据已参与研究，不能视为新的样本外验证。</p>
      <button className="primary" disabled={busy}>{busy ? "长期模型计算中…" : "运行长期持仓研究"}</button>
    </form>}
    {result && <>
      <p className="muted">本次结果：{result.config.model} · {result.start} — {result.end}（不含）· 窗口 {result.config.lookback} 日 · 预测 {result.config.horizon} 日 · 每 {result.config.rebalance_days} 日调仓 · 每批资金 {(result.config.tranche_weight * 100).toFixed(1)}%</p>
      <p>净值收益 <strong>{result.metrics.return_pct.toFixed(2)}%</strong> · 日终最大回撤 {result.metrics.max_drawdown_pct.toFixed(2)}% · {result.metrics.trade_count} 次分批成交
        {result.metrics.halted && " · 已触发风险熔断"}</p>
      <svg viewBox="0 0 800 180" role="img" aria-label="长期账户日终净值曲线" style={{ width: "100%", maxHeight: 240 }}>
        <polyline fill="none" stroke="var(--accent)" strokeWidth="2" points={result.curve.map((p, i) => `${10 + i / Math.max(result.curve.length - 1, 1) * 780},${170 - (p.equity - min) / Math.max(max - min, 1) * 160}`).join(" ")} />
        <text x="10" y="15" fontSize="12">${max.toFixed(0)}</text>
        <text x="10" y="178" fontSize="12">${min.toFixed(0)}</text>
      </svg>
      <p>期末持仓：{Object.entries(result.positions).map(([s, q]) => `${s} ${q}股`).join(" / ")}。净值包含未平仓头寸。</p>
      <DownloadButton href={`/api/position/${jobId}/export`}>导出全部分批成交 CSV</DownloadButton>
      <details><summary>查看最近100次成交及假设</summary>
        <div className="table-wrap"><table><thead><tr><th>日期</th><th>股票</th><th>方向</th><th>股数</th><th>价格</th><th>剩余持仓</th></tr></thead>
          <tbody>{result.trades.slice(-100).map((t, i) => <tr key={i}><td>{t.date}</td><td>{t.symbol}</td><td>{t.side === "buy" ? "买入" : "卖出"}</td><td>{t.quantity}</td><td>{t.price.toFixed(2)}</td><td>{t.position_after}</td></tr>)}</tbody></table></div>
        {result.assumptions.map((a) => <p className="muted" key={a}>{a}</p>)}
      </details>
    </>}
  </section>;
}
