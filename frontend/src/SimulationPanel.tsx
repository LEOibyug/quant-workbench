import { useEffect, useRef, useState } from "react";
import { api, post } from "./api";
import { phaseNames, type Phase } from "./types";
import { SimulationCharts, type SimulationData } from "./SimulationCharts";

export interface SimulationJob {
  id: string;
  symbol: string;
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
}
export function SimulationPanel({
  scope,
  sourceId,
  symbols,
  cash,
  bounds,
  validated,
  validFrom,
}: Props) {
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
        symbol,
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
        <h2>单股交易模拟</h2>
        <p className="muted">
          选择股票与日期，计算时持续更新曲线；完成后可暂停、调速或拖动回放。历史分钟行情模拟，非实时交易。
        </p>
        <div className="form-grid">
          <label>
            股票
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
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
          沿用此版本的策略、模型与交易成本。单次最多 92
          天；分钟缺失将拒绝模拟。每次从离线模型重新初始化在线适应。
        </p>
        <button
          className="primary"
          disabled={
            pending ||
            !!running ||
            !symbol ||
            (phase === "test" && !!bounds && !validated)
          }
          onClick={launch}
        >
          {pending ? "提交中…" : running ? "模拟进行中…" : "开始单股模拟"}
        </button>
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
                {j.symbol} · {j.start} — {j.end} · {j.status} ·{" "}
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
              {job.symbol} · {job.stage}
            </strong>
            <span>
              {job.completed_bars.toLocaleString()} /{" "}
              {job.total_bars ? job.total_bars.toLocaleString() : "—"} 分钟
            </span>
          </div>
          <progress max={job.total_bars || 1} value={job.completed_bars} />
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
      {job && data && data.market_curve.length > 0 && (
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
