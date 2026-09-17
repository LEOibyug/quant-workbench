import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

interface Estimate {
  rows: number;
  compressed_bytes_low: number;
  compressed_bytes_high: number;
  working_bytes_high: number;
}

function App() {
  const research = location.pathname !== "/workspace";
  const [connected, setConnected] = useState<boolean | null>(null);
  const [symbols, setSymbols] = useState(7);
  const [years, setYears] = useState(2);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error("API unavailable");
        const health = await r.json();
        setConnected(health.status === "ok");
      })
      .catch((e) => { if (e.name !== "AbortError") setConnected(false); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setEstimate(null);
    setError("");
    if (!Number.isInteger(symbols) || symbols < 1 || !Number.isFinite(years) || years <= 0) {
      setError("请输入有效的标的数量与历史年数。");
      return;
    }
    fetch(`/api/storage-estimate?symbols=${symbols}&years=${years}`, { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error("估算请求失败，请检查输入和后端连接。");
        setEstimate(await r.json());
      })
      .catch((e) => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [symbols, years]);

  const mb = (bytes: number) => (bytes / 1_000_000).toFixed(1);
  return (
    <div className="shell">
      <aside>
        <div className="brand">Q<span> / </span>WORKBENCH</div>
        <div className="local">本地美股研究</div>
        <nav aria-label="工作区导航">
          <a href="/research" aria-current={research ? "page" : undefined}>01　策略研究</a>
          <a href="/workspace" aria-current={!research ? "page" : undefined}>02　运行与展示</a>
        </nav>
        <div className="aside-footer">工程基础 v0.1<br />CPU 默认 · GPU 可选</div>
      </aside>
      <main>
        <header><span>LOCAL / US EQUITIES</span><span role="status">
          {connected === null ? "正在连接本地 API…" : connected ? "● 本地 API 已连接" : "○ 本地 API 未连接"}
        </span></header>
        <div className="intro">
          <p className="eyebrow">{research ? "RESEARCH" : "WORKSPACE"}</p>
          <h1>{research ? "从可复现的实验开始。" : "观察策略的每一次运行。"}</h1>
          <p>{research ? "规划数据范围与研究环境，为策略开发、验证和独立测试建立基础。" : "使用面板将运行已发布的策略版本，集中展示信号、订单、持仓与绩效。"}</p>
        </div>
        <div className="notice">当前为工程初始化版本。尚未接入市场数据、回测引擎或真实交易账户。</div>
        <section className="card">
          <div className="section-title"><h2>{research ? "分钟数据存储预算" : "数据与运行准备"}</h2><span>PLANNING</span></div>
          <p>1 分钟 OHLCV · 每年 252 个交易日 · 每日 390 分钟 · 不含盘前盘后</p>
          <div className="inputs">
            <label>标的数量<input type="number" min="1" max="10000" step="1" value={symbols} onChange={(e) => setSymbols(e.target.valueAsNumber)} /></label>
            <label>历史年数<input type="number" min="0.1" max="100" step="0.1" value={years} onChange={(e) => setYears(e.target.valueAsNumber)} /></label>
          </div>
          {error && <p role="alert">{error}</p>}
          <div className="metrics" aria-live="polite">
            <div><span>历史记录</span><strong>{estimate ? estimate.rows.toLocaleString() : "—"}</strong><small>行 OHLCV</small></div>
            <div><span>压缩文件预估</span><strong>{estimate ? `${mb(estimate.compressed_bytes_low)}–${mb(estimate.compressed_bytes_high)}` : "—"}</strong><small>MB · 24–64 字节／行</small></div>
            <div><span>含 3 份工作副本</span><strong>{estimate ? mb(estimate.working_bytes_high) : "—"}</strong><small>MB · 按上限预留</small></div>
          </div>
          <p className="caption">规划值，不是供应商数据实测。特征、模型、开发环境及逐笔数据另计。</p>
        </section>
        <div className="bottom-grid">
          <section className="card"><h2>研究候选池</h2><div className="tickers">{["NVDA", "TSLA", "AAPL", "AMD", "SOFI"].map((s) => <span key={s}>{s}</span>)}</div><p>SPY / QQQ 作为市场基准。候选池尚未经过策略收益验证。</p></section>
          <section className="card"><h2>{research ? "实验边界" : "运行边界"}</h2><p>{research ? "训练 → 验证 → 最终测试。股票池、参数与数据版本应随实验记录，测试结果不参与调参。" : "先做历史回放，再做实时模拟。实盘接口仅预留，当前没有可执行交易的入口。"}</p></section>
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
