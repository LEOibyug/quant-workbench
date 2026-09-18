import { useEffect, useRef, useState } from "react";
import { PortfolioCharts, type PortfolioTrade } from "./PortfolioCharts";
import { ProgressNotice } from "./ProgressNotice";
import { api, post } from "./api";
import { phaseNames, type Phase } from "./types";
import { SimulationCharts, type SimulationData } from "./SimulationCharts";

export interface SimulationJob {
  id: string;
  symbol: string;
  symbols?: string[];
  start: string;
  end: string;
  initial_cash: number;
  status: string;
  stage: string;
  completed_bars: number;
  total_bars: number;
  warnings: string[];
  error: string | null;
  data_source?: string;
  created_at?: string;
  completed_at?: string;
  download_progress?: { done: number; total: number | null; unit: string };
  config: Record<string, number | string>;
}
interface Props {
  scope: "research" | "workspace";
  sourceId: string;
  symbols: string[];
  cash: number;
  bounds?: Record<Phase, [string, string]>;
  validated?: boolean;
  validFrom?: string | null;
  portfolio?: boolean;
}
export function SimulationPanel({
  scope,
  sourceId,
  symbols,
  cash,
  bounds,
  validated,
  validFrom,
  portfolio = false,
}: Props) {
  const [selectedSymbols, setSelectedSymbols] = useState(symbols);
  const [symbol, setSymbol] = useState(symbols[0] || "");
  const [phase, setPhase] = useState<Phase>("validation");
  const [start, setStart] = useState(
    bounds?.validation[0] || validFrom || "2026-02-02",
  );
  const [end, setEnd] = useState(
    bounds?.validation[1] ||
      (() => {
        const d = new Date((validFrom || "2026-02-02") + "T00:00:00Z");
        d.setUTCDate(d.getUTCDate() + 7);
        return d.toISOString().slice(0, 10);
      })(),
  );
  const [capital, setCapital] = useState(cash);
  const [provider, setProvider] = useState("alpaca"),
    [feed, setFeed] = useState("sip");
  const [jobs, setJobs] = useState<SimulationJob[]>([]),
    [job, setJob] = useState<SimulationJob | null>(null);
  const [data, setData] = useState<SimulationData | null>(null);
  const [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const generation = useRef(0),
    mounted = useRef(true);
  const base = `/${scope}/simulations`;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current++;
    };
  }, []);
  useEffect(() => {
    let active = true;
    const token = generation.current;
    api<SimulationJob[]>(`${base}?source_id=${sourceId}`)
      .then((items) => {
        if (active) {
          setJobs(items);
          if (items[0] && token === generation.current)
            void selectJob(items[0].id);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [base, sourceId]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await api<SimulationJob>(`${base}/${job.id}`);
        const result = await api<SimulationData>(`${base}/${job.id}/result`);
        if (!active) return;
        setJob(next);
        setData(result);
        setJobs((items) => [next, ...items.filter((j) => j.id !== next.id)]);
        setError("");
        if (["queued", "running"].includes(next.status))
          timer = setTimeout(refresh, 700);
      } catch (e) {
        if (active) {
          setError((e as Error).message);
          timer = setTimeout(refresh, 2000);
        }
      }
    };
    refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [base, job?.id, job?.status]);
  async function launch() {
    const token = ++generation.current;
    setPending(true);
    setError("");
    setJob(null);
    setData(null);
    try {
      const next = await post<SimulationJob>(base, {
        source_id: sourceId,
        symbol: portfolio ? selectedSymbols[0] : symbol,
        ...(portfolio ? { symbols: selectedSymbols } : {}),
        start,
        end,
        initial_cash: capital,
        phase,
        provider,
        feed,
      });
      if (mounted.current && token === generation.current) {
        setJob(next);
        setJobs((items) => [next, ...items]);
      }
    } catch (e) {
      if (mounted.current && token === generation.current)
        setError((e as Error).message);
    } finally {
      if (mounted.current && token === generation.current) setPending(false);
    }
  }
  async function selectJob(id: string) {
    const token = ++generation.current;
    setJob(null);
    setData(null);
    setError("");
    if (!id) return;
    setPending(true);
    try {
      const [next, result] = await Promise.all([
        api<SimulationJob>(`${base}/${id}`),
        api<SimulationData>(`${base}/${id}/result`),
      ]);
      if (mounted.current && token === generation.current) {
        setJob(next);
        setData(result);
      }
    } catch (e) {
      if (mounted.current && token === generation.current)
        setError((e as Error).message);
    } finally {
      if (mounted.current && token === generation.current) setPending(false);
    }
  }
  const running = job && ["queued", "running"].includes(job.status);
  return (
    <section className="simulation-panel">
      <div className="card">
        <div className="eyebrow">MINUTE BY MINUTE</div>
        <h2>{portfolio ? "日内共享资金组合模拟" : "单股交易模拟"}</h2>
        <p className="muted">
          {portfolio ? "选择多只股票与日期，查看组合计算进度；完成后可暂停、调速或拖动详细回放。" : "选择股票与日期，计算时持续更新曲线；完成后可暂停、调速或拖动回放。"}历史分钟行情模拟，非实时交易。
        </p>
        <div className="form-grid">
          {portfolio ? <fieldset><legend>模拟股票</legend><div className="checks">
            {symbols.map((s) => <label key={s}><input type="checkbox" checked={selectedSymbols.includes(s)}
              onChange={(e) => setSelectedSymbols((prev) => e.target.checked ? [...prev, s] : prev.filter((v) => v !== s))} />{s}</label>)}
          </div></fieldset> : <label>
            股票
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>}
          {bounds && (
            <label>
              数据阶段
              <select
                value={phase}
                onChange={(e) => {
                  const p = e.target.value as Phase;
                  setPhase(p);
                  setStart(bounds[p][0]);
                  setEnd(bounds[p][1]);
                }}
              >
                {(Object.keys(phaseNames) as Phase[]).map((p) => (
                  <option
                    key={p}
                    value={p}
                    disabled={p === "test" && !validated}
                  >
                    {phaseNames[p]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            开始日期
            <input
              type="date"
              value={start}
              min={bounds?.[phase][0] || validFrom || undefined}
              max={bounds?.[phase][1]}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            结束日期（不含）
            <input
              type="date"
              value={end}
              min={start}
              max={bounds?.[phase][1]}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
          <label>
            初始资金 USD
            <input
              type="number"
              min="100"
              max="100000000"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
            />
          </label>
          {scope === "workspace" && (
            <>
              <label>
                行情 API
                <select
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                >
                  <option value="alpaca">Alpaca</option>
                  <option value="massive">Massive / Polygon</option>
                  <option value="demo">合成演示（2024 年 1—2 月）</option>
                </select>
              </label>
              {provider === "alpaca" && (
                <label>
                  行情源
                  <select
                    value={feed}
                    onChange={(e) => setFeed(e.target.value)}
                  >
                    <option value="sip">SIP 综合行情</option>
                    <option value="iex">IEX 单所行情</option>
                  </select>
                </label>
              )}
            </>
          )}
        </div>
        <p className="muted">
          沿用此版本的策略、模型与交易成本，不限制为三个月以内。日内模拟仍需完整分钟行情；每次从离线模型重新初始化在线适应。
        </p>
        <button
          className="primary"
          disabled={
            (portfolio && !selectedSymbols.length) || pending ||
            !!running ||
            !symbol ||
            (phase === "test" && !!bounds && !validated)
          }
          onClick={launch}
        >
          {pending ? "提交中…" : running ? "模拟进行中…" : "开始单股模拟"}
        </button>
        {pending && (
          <ProgressNotice
            value={{ status: "running", stage: "提交或加载模拟结果" }}
          />
        )}
        <label className="simulation-history">
          本页模拟记录
          <select
            value={job?.id || ""}
            disabled={pending}
            onChange={(e) => selectJob(e.target.value)}
          >
            <option value="">选择一次模拟</option>
            {jobs.map((j) => (
              <option value={j.id} key={j.id}>
                {(j.symbols || [j.symbol]).join(" / ")} · {j.start} — {j.end} · {j.status} ·{" "}
                {j.id.slice(0, 6)}
              </option>
            ))}
          </select>
        </label>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
      </div>
      {job && (
        <div className="card">
          <div className="simulation-status">
            <strong>
              {(job.symbols || [job.symbol]).join(" / ")} · {job.stage}
            </strong>
            <span>
              {job.completed_bars.toLocaleString()} /{" "}
              {job.total_bars ? job.total_bars.toLocaleString() : "—"} 分钟
            </span>
          </div>
          <ProgressNotice
            value={{
              status: job.status,
              stage: job.stage,
              done: job.total_bars
                ? job.completed_bars
                : job.download_progress?.done,
              total: job.total_bars || null,
              unit: job.total_bars ? "分钟" : job.download_progress?.unit,
              started_at: job.created_at,
              finished_at: job.completed_at,
            }}
          />
          <p className="muted">
            {job.start} — {job.end} · 初始资金 $
            {job.initial_cash.toLocaleString()} · {job.data_source || "加载中"}
          </p>
          {job.warnings.map((w) => (
            <p className="notice" key={w}>
              {w}
            </p>
          ))}
          {job.error && (
            <p className="notice error" role="alert">
              {job.error}
              。下方如有曲线，仅为失败前的部分过程，不是有效完整回测。
            </p>
          )}
          <details>
            <summary>本次成本参数</summary>
            <p>
              价差 {job.config.spread_bps} bps · 单边滑点{" "}
              {job.config.slippage_bps} bps · 每股佣金 $
              {job.config.commission_per_share} · 最低佣金 $
              {job.config.minimum_commission} · 卖出规费{" "}
              {job.config.sell_fee_bps} bps
            </p>
          </details>
        </div>
      )}
      {job && data?.portfolio_curve?.length ? <PortfolioCharts key={job.id}
        curve={data.portfolio_curve} trades={data.trades as unknown as PortfolioTrade[]}
        initialCash={job.initial_cash} allocationEnabled
        curveExport={`/api${base}/${job.id}/export/portfolio_curve`}
        tradesExport={`/api${base}/${job.id}/export/trades`}
        decisionsExport={`/api${base}/${job.id}/export/allocation_decisions`} /> : null}
      {job && data && !data.portfolio_curve?.length && data.market_curve.length > 0 && (
        <SimulationCharts
          key={job.id}
          data={data}
          job={job}
          exportBase={`/api${base}/${job.id}/export`}
        />
      )}
    </section>
  );
}
