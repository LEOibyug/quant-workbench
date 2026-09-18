import { useEffect, useState } from "react";
import { PortfolioCharts, type PortfolioPoint } from "./PortfolioCharts";
import { AllocationControls, readAllocation, type AllocationConfig } from "./AllocationControls";
import { api, post } from "./api";
import { DownloadButton, observeOperation, ProgressNotice, type ProgressState } from "./ProgressNotice";
import { strategyNames, type Dataset } from "./types";

interface PositionResult {
  synthetic?: boolean;
  source?: string;
  engine_version?: string;
  start: string;
  end: string;
  config: { model: string; lookback: number; horizon: number; rebalance_days: number; tranche_weight: number; costs?: { initial_cash: number } };
  metrics: { return_pct: number; max_drawdown_pct: number; trade_count: number; halted: boolean };
  portfolio_enabled?: boolean;
  curve: PortfolioPoint[];
  trades: { date: string; symbol: string; side: string; quantity: number; price: number; fee: number; impact_cost?: number; realized_pnl?: number | null; position_after: number; reason: string }[];
  positions: Record<string, number>;
  assumptions: string[];
}

export interface PositionDeployment {
  id: string;
  name: string;
  symbols: string[];
  position_config: {
    model: string; lookback: number; horizon: number; rebalance_days: number;
    confidence: number; tranche_weight: number; costs: { initial_cash: number };
    allocation?: AllocationConfig;
  };
}
export function PositionPanel({ datasets, modelEnabled = true, deployment }: {
  datasets: Dataset[]; modelEnabled?: boolean; deployment?: PositionDeployment;
}) {
  const pendingKey = deployment ? `quant.pending.position.${deployment.id}` : "quant.pending.position.operation";
  const lastKey = deployment ? `quant.last.position.${deployment.id}` : "quant.last.position.operation";
  const config = deployment?.position_config;
  const [marketMode, setMarketMode] = useState("daily");
  const [provider, setProvider] = useState("alpaca");
  const [feed, setFeed] = useState("sip");
  const [selectedSymbols, setSelectedSymbols] = useState(deployment?.symbols || []);
  const [jobs, setJobs] = useState<{ id: string; status: string; started_at: string; request: { name?: string; start: string; end: string } }[]>([]);
  const [published, setPublished] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [datasetId, setDatasetId] = useState("");
  const dataset = datasets.find((d) => d.id === datasetId) || datasets[0];
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const [result, setResult] = useState<PositionResult | null>(null);
  const [jobId, setJobId] = useState("");
  const [error, setError] = useState("");
  const [draftVersion, setDraftVersion] = useState(0);
  function newExperiment() {
    if (busy || publishing) return;
    if (localStorage.getItem(pendingKey)) {
      setError("先恢复尚未确认完成的长期任务，再新建实验"); return;
    }
    localStorage.removeItem(lastKey);
    setJobId(""); setResult(null); setProgress(null); setError(""); setPublished("");
    setDraftVersion((value) => value + 1);
  }
  async function observe(id: string) {
    setBusy(true); setError(""); setJobId(id); setPublished(""); setResult(null);
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
  }, [pendingKey, lastKey]);
  useEffect(() => {
    api<typeof jobs>(`/position/history${deployment ? `?deployment_id=${deployment.id}` : ""}`)
      .then(setJobs).catch((e) => setError(e.message));
  }, [deployment?.id, busy]);
  async function launch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || (!dataset && (!deployment || marketMode === "dataset"))) return;
    if (localStorage.getItem(pendingKey)) {
      setError("先恢复尚未确认完成的长期任务"); return;
    }
    const f = new FormData(event.currentTarget);
    const n = (key: string) => Number(f.get(key));
    setBusy(true); setError(""); setResult(null);
    try {
      const job = await post<{ id: string }>(deployment
        ? `/position/deployments/${deployment.id}/simulate` : "/position/run", deployment ? {
          dataset_id: marketMode === "dataset" ? dataset?.id : null,
          symbols: selectedSymbols, provider, feed, start: f.get("start"), end: f.get("end"),
        } : {
        name: f.get("name"),
        dataset_id: dataset!.id, symbols: dataset!.symbols,
        start: f.get("start"), end: f.get("end"),
        config: {
          allocation: readAllocation(f),
          model: modelEnabled ? f.get("model") : "equal_weight", lookback: n("lookback"), horizon: n("horizon"),
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
    <h2>{deployment ? "长期组合模拟" : "02 / 长期策略配置与验证"}</h2>
    <p>独立日线模型，持仓数日至数周；收盘形成目标仓位，次日开盘分批执行。
      与短期策略分别核算资金，研究结果不会提交真实订单。</p>
    {error && <p className="notice error" role="alert">{error}</p>}
    <label>{deployment ? "模拟记录" : "长期实验记录"}<select value={jobId} disabled={busy || publishing}
      onChange={(e) => { if (e.target.value) { localStorage.setItem(lastKey, e.target.value); void observe(e.target.value); } else if (!deployment) newExperiment(); }}>
      <option value="">{deployment ? "选择已有记录" : "新建长期实验"}</option>
      {jobs.map((job) => <option key={job.id} value={job.id}>{job.request.name || "长期策略"} · {job.request.start}—{job.request.end} · {job.status}</option>)}
    </select></label>
    {!deployment && <div className="section-heading">
      <p className="muted">{jobId ? "正在查看历史记录；新建实验将清空当前结果并重置下方配置，历史记录仍保留。" : "新实验：选择行情数据集、填写名称与参数，再点击下方“创建并运行长期实验”。"}</p>
      <button type="button" disabled={busy || publishing} onClick={newExperiment}>新建长期实验</button>
    </div>}
    <ProgressNotice value={progress} />
    {!busy && localStorage.getItem(pendingKey) && <button onClick={() => void observe(localStorage.getItem(pendingKey)!)}>恢复长期任务</button>}
    {deployment && <>
      <fieldset disabled={busy}><legend>模拟股票</legend>
        <div className="checks">{deployment.symbols.map((symbol) => <label key={symbol}>
          <input type="checkbox" checked={selectedSymbols.includes(symbol)} onChange={(e) => setSelectedSymbols(
            (current) => e.target.checked ? [...current, symbol] : current.filter((s) => s !== symbol),
          )} />{symbol}</label>)}</div>
        <p className="muted">可选择单股或多股；保留已发布的单股仓位上限，不把单股自动放大为满仓。</p>
      </fieldset>
      <div className="form-grid">
        <label>行情获取方式<select value={marketMode} disabled={busy} onChange={(e) => setMarketMode(e.target.value)}>
          <option value="daily">在线日线 · 自动获取及缓存</option>
          <option value="dataset">已有分钟数据集 · 沿用原成交量口径</option>
        </select></label>
        {marketMode === "daily" && <>
          <label>日线供应商<select value={provider} disabled={busy} onChange={(e) => setProvider(e.target.value)}>
            <option value="alpaca">Alpaca</option><option value="massive">Massive / Polygon</option>
          </select></label>
          {provider === "alpaca" && <label>行情源<select value={feed} disabled={busy} onChange={(e) => setFeed(e.target.value)}>
            <option value="sip">SIP 综合行情</option><option value="iex">IEX 单所行情</option>
          </select></label>}
        </>}
      </div>
      {marketMode === "daily" && <p className="notice">直接获取日线和预热历史，无需预先下载分钟数据。流动性按前一交易日总成交量 / 常规交易分钟数估算；与分钟数据模拟的成交结果可能不同。</p>}
    </>}
    {(!deployment || marketMode === "dataset") && <label>行情数据集<select value={dataset?.id || ""} disabled={busy} onChange={(e) => setDatasetId(e.target.value)}>
      {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
    </select></label>}
    {!dataset && (!deployment || marketMode === "dataset") && <p className="notice">暂无行情数据集，可切换在线日线或先在策略开发页获取行情。</p>}
    {(dataset || (deployment && marketMode === "daily")) && <form key={`${dataset?.id || "online"}-${draftVersion}`} onSubmit={launch}>
      {!deployment && <label>实验名称<input name="name" required maxLength={120} defaultValue="长期统计趋势研究" /></label>}
      <div className="form-grid">
        <label>开始日期<input name="start" type="date" required defaultValue={dataset?.start || "2025-01-02"} /></label>
        <label>结束日期（不含）<input name="end" type="date" required defaultValue={dataset ? new Date(Date.parse(dataset.end) + 86400000).toISOString().slice(0, 10) : new Date().toISOString().slice(0, 10)} /></label>
      </div>
      {deployment && <p className="muted">策略参数来自已发布版本，模拟时保持冻结。统计模型按当时可用历史重新估计，不携带研究期的未来信息。</p>}
      <fieldset disabled={!!deployment || busy}>
      <div className="form-grid">
        <label>{modelEnabled || deployment ? "长期模型 / 策略" : "规则策略"}<select key={String(modelEnabled)} name="model" defaultValue={config?.model || (modelEnabled ? "trend" : "equal_weight")} required>
          {(modelEnabled || deployment) && <><option value="trend">统计趋势 + 波动率仓位</option>
          <option value="bayesian">贝叶斯多日收益回归</option></>}
          {(!modelEnabled || deployment) && <option value="equal_weight">等权分批再平衡（无预测模型）</option>}
        </select></label>

        <label>独立资金 USD<input name="cash" type="number" min={100} defaultValue={config?.costs.initial_cash ?? 100000} required /></label>
        <label>历史窗口 交易日<input name="lookback" type="number" min={10} max={60} defaultValue={config?.lookback ?? 20} required /></label>
        <label>预测跨度 交易日<input name="horizon" type="number" min={1} max={20} defaultValue={config?.horizon ?? 5} required /></label>
        <label>调仓间隔 交易日<input name="rebalance" type="number" min={1} max={20} defaultValue={config?.rebalance_days ?? 5} required /></label>
        <label>不确定性扣减倍数<input name="confidence" type="number" min={0} max={3} step={0.1} defaultValue={config?.confidence ?? 0.5} required /></label>
        <label>每日单股最大调整 资金%<input name="tranche" type="number" min={0.1} max={20} step={0.1} defaultValue={config ? config.tranche_weight * 100 : 5} required /></label>
      </div>
      <AllocationControls key={dataset?.id || deployment?.id} symbols={deployment?.symbols || dataset?.symbols || []}
        initial={config?.allocation} long />
      </fieldset>
      <p className="muted">{(deployment ? selectedSymbols : dataset!.symbols).join(" / ")}。默认单股目标上限20%、止损10%、组合回撤10%后熔断。
        价差2bps、滑点2bps，佣金每股$0.005、每次最低$1。模型历史不足时持币；已有数据已参与研究，不能视为新的样本外验证。</p>
      <button className="primary" disabled={busy || publishing || (!!deployment && !selectedSymbols.length)}>{busy ? "计算中…" : deployment ? "运行已发布策略模拟" : "创建并运行长期实验"}</button>
    </form>}
    {result && <>
      <p className="muted">本次模拟股票：{Object.keys(result.positions).join(" / ")} · 数据来源：{result.source}</p>
      {result.engine_version?.startsWith("daily-position-v3-daily") && <p className="notice">日线成交量估算模式：使用前日平均分钟量限制成交，不代表真实开盘可成交量。</p>}
      {result.synthetic && <p className="notice">本次使用合成行情，仅作功能演示。</p>}
      {!deployment && <div className="section-heading">
        <p>已完成长期验证，可发布本次冻结参数到展示页；发布不代表已证明盈利。</p>
        <button disabled={busy || publishing} onClick={async () => {
          setPublishing(true); setError("");
          try {
            const item = await post<{ id: string }>(`/position/${jobId}/publish`, {});
            setPublished(item.id);
          } catch (e) { setError((e as Error).message); }
          finally { setPublishing(false); }
        }}>{publishing ? "发布中…" : "发布到展示页"}</button>
        {published && <a className="button" href={`/workspace?deployment=${published}`}>查看已发布版本 →</a>}
      </div>}
      <p className="muted">本次结果：{strategyNames[result.config.model] || result.config.model} · {result.start} — {result.end}（不含）· 窗口 {result.config.lookback} 日 · 预测 {result.config.horizon} 日 · 每 {result.config.rebalance_days} 日调仓 · 每批资金 {(result.config.tranche_weight * 100).toFixed(1)}%</p>
      <p>净值收益 <strong>{result.metrics.return_pct.toFixed(2)}%</strong> · 日终最大回撤 {result.metrics.max_drawdown_pct.toFixed(2)}% · {result.metrics.trade_count} 次分批成交
        {result.metrics.halted && " · 已触发风险熔断"}</p>
      {result.curve[0]?.assets ? <PortfolioCharts key={jobId} curve={result.curve} trades={result.trades}
        initialCash={result.config.costs?.initial_cash || result.curve[0].equity}
        allocationEnabled={result.portfolio_enabled}
        curveExport={`/api/position/${jobId}/export/curve`}
        tradesExport={`/api/position/${jobId}/export`}
        decisionsExport={`/api/position/${jobId}/export/allocations`} /> : <>
      <p className="notice">此历史记录未保存逐股复盘数据，重新运行可生成详细曲线。</p>
      <svg viewBox="0 0 800 180" role="img" aria-label="长期账户日终净值曲线" style={{ width: "100%", maxHeight: 240 }}>
        <polyline fill="none" stroke="var(--accent)" strokeWidth="2" points={result.curve.map((p, i) => `${10 + i / Math.max(result.curve.length - 1, 1) * 780},${170 - (p.equity - min) / Math.max(max - min, 1) * 160}`).join(" ")} />
      </svg></>}
      <p>期末持仓：{Object.entries(result.positions).map(([s, q]) => `${s} ${q}股`).join(" / ")}。净值包含未平仓头寸。</p>
      <DownloadButton href={`/api/position/${jobId}/export`}>导出全部分批成交 CSV</DownloadButton>
      <details><summary>完整执行假设</summary>
        {result.assumptions.map((a) => <p className="muted" key={a}>{a}</p>)}
      </details>
    </>}
  </section>;
}
