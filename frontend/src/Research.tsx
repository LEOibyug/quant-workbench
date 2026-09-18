import { useEffect, useState } from "react";
import { ExperimentRunner } from "./ExperimentRunner";
import { AllocationControls, readAllocation } from "./AllocationControls";
import { PositionPanel } from "./PositionPanel";
import { StockPicker } from "./StockPicker";
import { api, post } from "./api";
import {
  ProgressNotice,
  runOperation,
  pendingOperation,
  observeOperation,
  type ProgressState,
} from "./ProgressNotice";
import { strategyNames } from "./types";
import type { Dataset, Experiment } from "./types";
const tomorrow = (day: string) =>
  new Date(Date.parse(day) + 86400000).toISOString().slice(0, 10);
export function Research() {
  const [datasets, setDatasets] = useState<Dataset[]>([]),
    [selected, setSelected] = useState("");
  const [longDatasetId, setLongDatasetId] = useState("");
  const [symbols, setSymbols] = useState<string[]>([]),
    [dates, setDates] = useState(["", "", "", ""]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [reconnect, setReconnect] = useState(0);
  const [activity, setActivity] = useState<"data" | "train">("data");
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const [created, setCreated] = useState<Experiment | null>(null);
  const [provider, setProvider] = useState("alpaca");
  const [providers, setProviders] = useState<
    { id: string; name: string; configured: boolean; note: string }[]
  >([]);
  const [enabled, setEnabled] = useState(true);
  const [horizonType, setHorizonType] = useState("short");
  const [longEnabled, setLongEnabled] = useState(true);
  const [commission, setCommission] = useState("0.005");
  const [minimum, setMinimum] = useState("1");
  const dataset = datasets.find((d) => d.id === selected && (d.timeframe || "1Min") === "1Min");
  const [downloadTimeframe, setDownloadTimeframe] = useState("1Min");
  const currentLongId = longDatasetId || datasets.find((d) => d.timeframe === "1Day")?.id || "";
  const activeDataset = horizonType === "long" ? datasets.find((d) => d.id === currentLongId) : dataset;
  const choose = (d: Dataset) => {
    if (d.timeframe === "1Day") {
      setLongDatasetId(d.id); setHorizonType("long"); setDownloadTimeframe("1Day"); return;
    }
    setHorizonType("short"); setDownloadTimeframe("1Min");
    setSelected(d.id);
    setSymbols(d.symbols);
    setDates([
      d.start,
      d.dates[Math.floor(d.dates.length * 0.6)],
      d.dates[Math.floor(d.dates.length * 0.8)],
      tomorrow(d.end),
    ]);
    setCreated(null);
  };
  useEffect(() => {
    api<{ id: string; name: string; configured: boolean; note: string }[]>(
      "/providers",
    )
      .then(setProviders)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    api<Dataset[]>("/datasets")
      .then(setDatasets)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    const saved = pendingOperation();
    if (!saved) return;
    let active = true;
    setBusy(true);
    setError("");
    setActivity(saved.kind === "train" ? "train" : "data");
    setProgress({ status: "running", stage: "恢复后台任务进度" });
    observeOperation<Dataset | Experiment>(saved.id, (p) => {
      if (active) setProgress(p);
    })
      .then((result) => {
        if (!active) return;
        if (saved.kind === "train") setCreated(result as Experiment);
        else {
          const d = result as Dataset;
          setDatasets((prev) => [d, ...prev.filter((x) => x.id !== d.id)]);
          choose(d);
        }
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          setProgress({
            status: "failed",
            stage: "进度观察中断",
            error: e.message,
          });
        }
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [reconnect]);
  async function loadData(
    work: () => Promise<Dataset>,
    stage = "加载并校验行情数据",
  ) {
    setActivity("data");
    const started_at = new Date().toISOString();
    setProgress({ status: "running", stage, started_at });
    setBusy(true);
    setError("");
    try {
      const d = await work();
      setDatasets((prev) => [d, ...prev.filter((x) => x.id !== d.id)]);
      choose(d);
      setProgress({
        status: "completed",
        stage: "行情已保存",
        done: d.rows,
        unit: "条",
        started_at,
        finished_at: new Date().toISOString(),
      });
    } catch (e) {
      setError((e as Error).message);
      setProgress((p) => ({
        ...p,
        status: "failed",
        stage: "任务失败",
        error: (e as Error).message,
        finished_at: new Date().toISOString(),
      }));
    } finally {
      setBusy(false);
    }
  }
  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setActivity("train");
    setProgress({
      status: "running",
      stage: "提交训练任务",
      started_at: new Date().toISOString(),
    });
    setBusy(true);
    setError("");
    const n = (key: string) => Number(f.get(key));
    try {
      const result = await runOperation<Experiment>(
        "train",
        {
          name: f.get("name"),
          dataset_id: selected,
          symbols,
          start: dates[0],
          train_end: dates[1],
          validation_end: dates[2],
          end: dates[3],
          config: {
            allocation: readAllocation(f),
            strategy: f.get("strategy"),
            fast: n("fast"),
            slow: n("slow"),
            initial_cash: n("cash"),
            spread_bps: n("spread"),
            slippage_bps: n("slippage"),
            commission_per_share: n("commission"),
            minimum_commission: n("minimum"),
            sell_fee_bps: n("sell_fee"),
            participation: n("participation") / 100,
            stop_loss_bps: n("stop_loss"),
            opening_minutes: n("opening"),
            flatten_minutes: n("flatten"),
            reversion_bps: n("reversion"),
            max_hold_minutes: n("max_hold"),
            cooldown_minutes: n("cooldown"),
            stop_atr: n("stop_atr"),
            take_atr: n("take_atr"),
            risk_per_trade_bps: n("risk_budget"),
            rule_cost_multiplier: n("rule_cost"),
            regime_window: n("regime_window"),
            min_reward_risk: n("reward_risk"),
            reversion_atr: n("reversion_atr"),
            stat_window: n("stat_window"),
            max_scaling_lots: n("stat_lots"),
            stat_horizon: n("stat_horizon"),
            stat_entry_z: n("stat_entry_z"),
            stat_confidence: n("stat_confidence"),
            stat_process_noise: n("stat_process_noise"),
          },
          model: enabled
            ? {
                enabled: true,
                k: n("k"),
                max_iter: n("max_iter"),
                horizon: n("horizon"),
                architecture: f.get("architecture"),
                decision_mode: f.get("decision_mode"),
                return_normalization:
                  f.get("architecture") === "gru" &&
                  f.get("return_normalization") === "on",
                neural_online_learning_rate: n("neural_lr"),
                online_batch_size: n("online_batch"),
                probability_threshold: n("threshold"),
                online_learning_rate: n("learning_rate"),
                cost_aware: f.get("cost_aware") === "on",
                cost_multiplier: n("cost_multiplier"),
                min_edge_bps: n("min_edge"),
              }
            : { enabled: false },
        },
        setProgress,
      );
      setCreated(result);
    } catch (e) {
      setError((e as Error).message);
      setProgress((p) => ({
        ...p,
        status: "failed",
        stage: "任务失败",
        error: (e as Error).message,
        finished_at: new Date().toISOString(),
      }));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">RESEARCH LAB</div>
          <h1>从数据到可复现的策略</h1>
          <p>先冻结开发范围、策略与成本，再依次验证。在当前工作台完成训练、回测与复盘。</p>
        </div>
        <span className="badge">INTRADAY / MULTI-DAY · LONG ONLY</span>
      </div>
      <nav className="anchor-nav" aria-label="页面分区导航">
        {(horizonType === "long" ? [
          ["#data", "行情数据"], ["#strategy-mode", "策略配置"], ["#position", "验证与发布"],
        ] : [
          ["#data", "行情数据"],
          ["#strategy-mode", "策略配置"],
          ["#evaluation", "实验验证"],
          ["#simulation", "单股模拟"],
          ["#results", "结果明细"],
        ]).map(([href, label]) => (
          <a key={href} href={href}>
            {label}
          </a>
        ))}
      </nav>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {!busy && pendingOperation() && (
        <button onClick={() => setReconnect((n) => n + 1)}>重新连接任务</button>
      )}
      {activity === "train" && !dataset && <ProgressNotice value={progress} />}
      <section className="card" id="data">
        <div className="section-heading">
          <h2>01 / 行情数据</h2>
          <button
            disabled={busy}
            onClick={() => loadData(() => post<Dataset>("/datasets/demo"))}
          >
            {busy && activity === "data" ? "处理中…" : "使用合成示例"}
          </button>
        </div>
        <p className="muted">
          通过数据提供商 API
          直接下载到工作台数据目录。示例只用于检查流程，不代表真实股票表现。
        </p>
        <div className="form-grid">
          <label>
            行情数据集（短期 / 长期）
            <select
              value={horizonType === "long" ? currentLongId : selected}
              disabled={busy}
              onChange={(e) => {
                const d = datasets.find((x) => x.id === e.target.value);
                if (d) choose(d);
              }}
            >
              <option value="">选择数据集</option>
              <optgroup label="长期 · 日线">
                {datasets.filter((d) => d.timeframe === "1Day").map((d) => <option key={d.id} value={d.id}>
                  [日线] {d.name} · {d.symbols.length} 股 · {d.rows.toLocaleString()} 条 · {d.id.slice(0, 6)}
                </option>)}
              </optgroup>
              <optgroup label="短期 · 分钟线">
                {datasets.filter((d) => (d.timeframe || "1Min") === "1Min").map((d) => <option key={d.id} value={d.id}>
                  [分钟线] {d.name} · {d.symbols.length} 股 · {d.id.slice(0, 6)}
                </option>)}
              </optgroup>
            </select>
          </label>
          <details>
            <summary>可选：导入已有 CSV</summary>
            <label>
              导入 CSV
              <input
                disabled={busy}
                type="file"
                accept=".csv"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    const f = new FormData();
                    f.append("file", file);
                    loadData(() =>
                      api<Dataset>("/datasets/import", {
                        method: "POST",
                        body: f,
                      }),
                    );
                  }
                }}
              />
            </label>
            <small>时间戳必须带时区，表示分钟结束时间。</small>
          </details>
        </div>
        <small>
          列：timestamp, symbol, open, high, low, close,
          volume。仅支持美股常规交易时段，缺失分钟会拒绝回测。
        </small>
        <div className="provider-form">
          <h3>API 直连行情</h3>
          <p className="muted">
            密钥在工作台运行环境中配置。Alpaca 按最多 3 个自然月分段下载并合并，进度显示当前区间；结束日期不含。下载后保存快照，不自动补造缺失行情。单数据集仍受行数上限和历史权限限制。
          </p>
          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              loadData(() =>
                runOperation<Dataset>(
                  "download",
                  {
                    provider,
                    timeframe: downloadTimeframe,
                    symbols: String(f.get("symbols"))
                      .split(",")
                      .map((x) => x.trim().toUpperCase()),
                    start: f.get("start"),
                    end: f.get("end"),
                    feed: f.get("feed") || "iex",
                  },
                  setProgress,
                ),
              );
            }}
          >
            <label>
              供应商
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                <option value="alpaca">Alpaca</option>
                <option value="massive">Massive / Polygon</option>
              </select>
            </label>
            <label>数据周期<select value={downloadTimeframe} onChange={(e) => setDownloadTimeframe(e.target.value)} disabled={busy}>
              <option value="1Min">短期 · 1 分钟 K 线</option>
              <option value="1Day">长期 · 日 K 线（OHLCV）</option>
            </select></label>
            <p className="muted">{downloadTimeframe === "1Day" ? "长期使用供应商原生日线，每个交易日一根 K 线，包含开高低收及成交量。建议下载日期比实验开始提前至少 240 个自然日，以供模型预热。" : "短期使用常规交易时段分钟线，回测要求逐分钟完整；缺失记录不会自动补造。"}</p>
            <StockPicker disabled={busy} />
            <label>
              起始日期
              <input name="start" type="date" required />
            </label>
            <label>
              结束日期（不含）
              <input name="end" type="date" required />
            </label>
            {provider === "alpaca" && (
              <label>
                行情源
                <select name="feed">
                  <option value="iex">IEX</option>
                  <option value="sip">SIP</option>
                </select>
              </label>
            )}
            <button disabled={busy}>
              {busy && activity === "data"
                ? "下载 / 处理数据中…"
                : "通过 API 下载"}
            </button>
          </form>
          <p className="muted">
            {providers.find((p) => p.id === provider)?.configured
              ? "● 密钥已配置"
              : "○ 尚未配置密钥"}{" "}
            · {providers.find((p) => p.id === provider)?.note}
          </p>
          <small>
            {provider === "alpaca"
              ? "后端环境变量：APCA_API_KEY_ID / APCA_API_SECRET_KEY"
              : "后端环境变量：MASSIVE_API_KEY（兼容 POLYGON_API_KEY）"}
          </small>
        </div>
        {activity === "data" && <ProgressNotice value={progress} />}
        {activeDataset && (
          <div className="notice">
            {activeDataset.timeframe === "1Day" ? "长期日线" : "短期分钟线"} · {activeDataset.synthetic ? "合成数据" : activeDataset.source} ·{" "}
            {activeDataset.rows.toLocaleString()} 条 · {activeDataset.start} — {activeDataset.end}
          </div>
        )}
      </section>
      <section className="card" id="strategy-mode">
        <h2>策略开发</h2>
        <div className="form-grid">
          <label>交易周期<select aria-label="交易周期" value={horizonType} onChange={(e) => setHorizonType(e.target.value)}>
            <option value="short">短期 · 日内交易</option>
            <option value="long">长期 · 隔夜持仓与分批调仓</option>
          </select></label>
          <label>模型介入<select aria-label="模型介入" value={String(horizonType === "short" ? enabled : longEnabled)}
            onChange={(e) => (horizonType === "short" ? setEnabled : setLongEnabled)(e.target.value === "true")}>
            <option value="false">{horizonType === "short" ? "关闭 · 不叠加时序模型" : "关闭 · 等权规则"}</option>
            <option value="true">开启 · 模型参与决策</option>
          </select></label>
        </div>
        <p className="muted">两种周期均可配置、验证、发布并在展示页模拟。短期开关控制额外的时序模型，OU等统计策略仍保留内置估计；长期模型生成目标仓位，关闭后使用等权分批再平衡。</p>
      </section>
      <div hidden={horizonType !== "short"}>
      {dataset && (
        <form onSubmit={create}>
          <section className="card" id="setup">
            <h2>02 / 冻结实验范围</h2>
            <div className="form-grid">
              <label>
                实验名称
                <input
                  name="name"
                  defaultValue="美股分钟策略 + 在线时序模型"
                  required
                  maxLength={80}
                />
              </label>
              <label>
                策略
                <select name="strategy" defaultValue="regime_adaptive" onChange={(e) => {
                  if (["ou_reversion", "ou_scaling", "kalman_trend", "bayesian_session"].includes(e.target.value)) setEnabled(false);
                }}>
                  {Object.entries(strategyNames).filter(([k]) => !["cross_momentum", "channel_trend", "residual_reversal", "minimum_variance", "fixed_ensemble", "adaptive_specialist", "synthetic_regime", "generated_policy"].includes(k)).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="checks">
              {dataset.symbols.map((s) => (
                <label key={s}>
                  <input
                    type="checkbox"
                    checked={symbols.includes(s)}
                    onChange={(e) =>
                      setSymbols((prev) =>
                        e.target.checked
                          ? [...prev, s]
                          : prev.filter((x) => x !== s),
                      )
                    }
                  />
                  {s}
                </label>
              ))}
            </div>
            <div className="form-grid four">
              {[
                "开发起点",
                "验证起点 / 开发终点",
                "最终测试起点 / 验证终点",
                "结束日期（不含）",
              ].map((name, i) => (
                <label key={name}>
                  {name}
                  <input
                    type="date"
                    required
                    value={dates[i] || ""}
                    onChange={(e) =>
                      setDates((d) =>
                        d.map((v, j) => (i === j ? e.target.value : v)),
                      )
                    }
                  />
                </label>
              ))}
            </div>
            <p className="muted">
              开发期训练模型并生成股票特征。验证与最终测试各自从同一个离线模型开始，按预定规则在线适应。最终测试不能反向影响参数选择。
            </p>
            <div className="form-grid four">
              <label>
                初始资金 USD
                <input
                  name="cash"
                  type="number"
                  defaultValue={100000}
                  min={1000}
                />
              </label>
              <label>
                快均线周期
                <input
                  name="fast"
                  type="number"
                  defaultValue={8}
                  min={2}
                  max={60}
                />
              </label>
              <label>
                慢均线周期
                <input
                  name="slow"
                  type="number"
                  defaultValue={21}
                  min={3}
                  max={120}
                />
              </label>
              <label>
                止损 bps
                <input name="stop_loss" type="number" defaultValue={100} />
              </label>
              <label>
                开盘区间 分钟
                <input name="opening" type="number" defaultValue={15} />
              </label>
              <label>
                收盘前清仓 分钟
                <input
                  name="flatten"
                  type="number"
                  min={1}
                  max={30}
                  defaultValue={5}
                />
              </label>
              <label>
                VWAP 偏离 bps
                <input name="reversion" type="number" defaultValue={15} />
              </label>
            </div>
            <details>
              <summary>统计策略参数（OU / Kalman / 贝叶斯）</summary>
              <p className="muted">
                使用当前及此前已完成行情估计收益与不确定性，预期收益须覆盖成本才入场。
                统计策略自带模型，无需额外启用下方时序模型。贝叶斯策略固定使用前60个已完成交易日、开盘30分钟预测，不确定性扣减倍数可调。
                研究候选，尚未证明未来盈利。
              </p>
              <div className="form-grid">
                <label>估计窗口 分钟<input name="stat_window" type="number" min={30} max={390} defaultValue={120} /></label>
                <label>分批策略最多批数<input name="stat_lots" type="number" min={1} max={5} defaultValue={3} /></label>
                <label>预测跨度 分钟<input name="stat_horizon" type="number" min={5} max={60} defaultValue={15} /></label>
                <label>OU 入场偏离 标准差<input name="stat_entry_z" type="number" min={0.5} max={4} step={0.1} defaultValue={1.5} /></label>
                <label>不确定性扣减倍数<input name="stat_confidence" type="number" min={0} max={3} step={0.1} defaultValue={0.5} /></label>
                <label>Kalman 趋势噪声比<input name="stat_process_noise" type="number" min={0.00001} max={0.1} step={0.00001} defaultValue={0.001} /></label>
              </div>
            </details>
            <details open>
              <summary>增强策略风控（含趋势回调 / 状态组合）</summary>
              <p className="muted">
                参考过去20个交易日的波动背景，使用已结束分钟确认信号。每天最多4次入场，日亏损1%后停止入场；风险预算不保证限制跳空损失。
              </p>
              <div className="form-grid">
                <label>
                  状态判断窗口 分钟
                  <input
                    name="regime_window"
                    type="number"
                    min={30}
                    max={120}
                    defaultValue={60}
                  />
                </label>
                <label>
                  最低目标/风险比
                  <input
                    name="reward_risk"
                    type="number"
                    min={0.5}
                    max={5}
                    step={0.1}
                    defaultValue={1.2}
                  />
                </label>
                <label>
                  回归偏离 ATR倍数
                  <input
                    name="reversion_atr"
                    type="number"
                    min={0.5}
                    max={5}
                    step={0.1}
                    defaultValue={1.5}
                  />
                </label>
                <label>
                  最长持仓 分钟
                  <input
                    name="max_hold"
                    type="number"
                    min={5}
                    max={120}
                    defaultValue={45}
                  />
                </label>
                <label>
                  平仓后冷却 分钟
                  <input
                    name="cooldown"
                    type="number"
                    min={0}
                    max={60}
                    defaultValue={10}
                  />
                </label>
                <label>
                  止损 ATR倍数
                  <input
                    name="stop_atr"
                    type="number"
                    min={0.5}
                    max={5}
                    step={0.1}
                    defaultValue={2}
                  />
                </label>
                <label>
                  止盈 ATR倍数
                  <input
                    name="take_atr"
                    type="number"
                    min={1}
                    max={10}
                    step={0.1}
                    defaultValue={4}
                  />
                </label>
                <label>
                  单笔风险预算 bps
                  <input
                    name="risk_budget"
                    type="number"
                    min={1}
                    max={100}
                    defaultValue={25}
                  />
                </label>
                <label>
                  规则目标 / 成本倍数
                  <input
                    name="rule_cost"
                    type="number"
                    min={1}
                    max={5}
                    step={0.1}
                    defaultValue={1.5}
                  />
                </label>
              </div>
            </details>
            <details open>
              <summary>交易成本与成交限制</summary>
              <p className="muted">
                佣金对照仅替换以下两项，点差、滑点与卖出规费保持原值。 Alpaca
                需符合免佣账户条件；IBKR 为首档基础佣金，未另计交易所与清算费。
                当前引擎按每次成交收最低佣金，分批成交可能高于券商按订单计费。
              </p>
              <div className="button-row">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setCommission("0.005");
                    setMinimum("1");
                  }}
                >
                  保守佣金 · $0.005 / 最低 $1
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setCommission("0");
                    setMinimum("0");
                  }}
                >
                  Alpaca 免佣情景
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setCommission("0.0035");
                    setMinimum("0.35");
                  }}
                >
                  IBKR 阶梯首档 · $0.0035 / 最低 $0.35
                </button>
              </div>
              <div className="form-grid four">
                <label>
                  完整价差 bps
                  <input
                    name="spread"
                    type="number"
                    step="0.1"
                    defaultValue={2}
                  />
                </label>
                <label>
                  单边滑点 bps
                  <input
                    name="slippage"
                    type="number"
                    step="0.1"
                    defaultValue={2}
                  />
                </label>
                <label>
                  佣金 USD/股
                  <input
                    name="commission"
                    type="number"
                    min={0}
                    step="0.0001"
                    value={commission}
                    onChange={(e) => setCommission(e.target.value)}
                  />
                </label>
                <label>
                  最低佣金 USD/次成交
                  <input
                    name="minimum"
                    type="number"
                    min={0}
                    step="0.01"
                    value={minimum}
                    onChange={(e) => setMinimum(e.target.value)}
                  />
                </label>
                <label>
                  卖出规费近似 bps
                  <input
                    name="sell_fee"
                    type="number"
                    step="0.1"
                    defaultValue={0.3}
                  />
                </label>
                <label>
                  前分钟成交量参与率 %
                  <input
                    name="participation"
                    type="number"
                    step="0.1"
                    min={0.1}
                    max={10}
                    defaultValue={1}
                  />
                </label>
              </div>
            </details>
          </section>
          <section className="card"><AllocationControls key={selected} symbols={symbols} /></section>
          <section className="card" id="model">
            <div className="section-heading">
              <h2>03 / 模型介入与执行</h2>
              <span className="badge">{enabled ? "时序模型参与决策" : "不叠加时序模型"}</span>
            </div>
            {!enabled && <p className="muted">使用所选策略及其内置估计，按已配置的成本和风控执行。</p>}
            <p hidden={!enabled}>
              模型综合过去 k
              根分钟线与约1/5/20交易日的历史背景，输出指定跨度的上涨概率与收益。首
              k 根积累窗口，k—2k 为适应期，前 2k
              根不参与交易；标签在预测跨度到期后才用于更新。GRU/MLP同时接收最近已成熟预测、真实值和误差。
            </p>
            {enabled && (
              <div className="form-grid">
                <label>
                  模型结构
                  <select name="architecture" defaultValue="gru">
                    <option value="gru">因果卷积 + 双尺度 GRU + 注意力</option>
                    <option value="mlp">双头 MLP · 64→32 · 误差反馈</option>
                    <option value="rbf">RBF非线性 + 在线双头</option>
                    <option value="linear">线性双头基线</option>
                  </select>
                </label>
                <label>
                  联合决策方式
                  <select name="decision_mode" defaultValue="adaptive">
                    <option value="adaptive">
                      规则 + 自适应分位门槛 + 仓位调节（默认）
                    </option>
                    <option value="risk_scaled">
                      规则 + 模型仓位调节（需增强规则）
                    </option>
                    <option value="strict">严格概率 + 收益门槛</option>
                  </select>
                </label>
                <label className="inline">
                  <input
                    name="return_normalization"
                    type="checkbox"
                    defaultChecked
                  />
                  GRU 收益目标按开发期波动率标准化
                </label>
                <label>
                  预测跨度 分钟
                  <select name="horizon" defaultValue="5">
                    <option value="1">1</option>
                    <option value="5">5</option>
                    <option value="15">15</option>
                  </select>
                </label>
                <label>
                  窗口 k
                  <input
                    name="k"
                    type="number"
                    min={5}
                    max={120}
                    defaultValue={30}
                  />
                </label>
                <label>
                  严格模式上涨概率门槛
                  <input
                    name="threshold"
                    type="number"
                    min={0.5}
                    max={0.95}
                    step=".01"
                    defaultValue={0.55}
                  />
                </label>
                <label className="inline">
                  <input name="cost_aware" type="checkbox" defaultChecked />
                  严格模式：预期收益必须覆盖成本
                </label>
                <label>
                  成本安全倍数
                  <input
                    name="cost_multiplier"
                    type="number"
                    min={1}
                    max={10}
                    step={0.1}
                    defaultValue={1.5}
                  />
                </label>
                <label>
                  最低额外优势 bps
                  <input
                    name="min_edge"
                    type="number"
                    min={0}
                    max={100}
                    step={0.1}
                    defaultValue={1}
                  />
                </label>
                <label>
                  离线训练轮数
                  <input
                    name="max_iter"
                    type="number"
                    min={1}
                    max={20}
                    defaultValue={3}
                  />
                </label>
                <label>
                  序列网络在线学习率
                  <input
                    name="neural_lr"
                    type="number"
                    min={0.000001}
                    max={0.001}
                    step={0.000001}
                    defaultValue={0.00003}
                  />
                </label>
                <label>
                  序列网络更新间隔（成熟样本）
                  <input
                    name="online_batch"
                    type="number"
                    min={1}
                    max={64}
                    defaultValue={16}
                  />
                </label>
                <label>
                  线性/MLP在线学习率
                  <input
                    name="learning_rate"
                    type="number"
                    min={0.000001}
                    max={0.01}
                    step=".000001"
                    defaultValue={0.001}
                  />
                </label>
              </div>
            )}
            <p className="muted" hidden={!enabled}>
              仓位调节模式：规则负责成本空间与风险预算，模型在预算内决定25%—100%仓位，明显看空时否决；低置信度不再一律禁买。严格模式继续要求概率与预测收益双门槛。仓位调节不代表模型预测的期望收益已覆盖成本，仍需验证。
            </p>
            <p className="muted" hidden={!enabled}>
              GRU直接编码分钟与已完成5分钟序列，保留长历史与误差反馈，使用近期成熟样本回放；默认设备自动选择
              CUDA →
              CPU（已面向CUDA生态，MPS不再支持），元数据与运行结果记录实际设备。MLP采用两个64→32隐藏层网络，分别输出概率与收益；线性/RBF版本使用逻辑分类与Huber回归。每股独立更新；跨日保留模型权重和历史背景，重建短窗口与误差反馈，不生成隔夜标签。上涨概率不等同于净盈利概率；严格模式的成本过滤要求预测收益
              bps 大于估计往返成本 × 安全倍数 + 最低额外优势。
            </p>
            <button className="primary" disabled={busy || !symbols.length}>
              {busy && activity === "train" ? "训练进行中…" : "训练并冻结实验"}
            </button>
            {activity === "train" && <ProgressNotice value={progress} />}
          </section>
        </form>
      )}
      {created && (
        <section className="card">
          <div className="section-heading">
            <h2>实验已冻结</h2>
            <a className="button primary" href="#evaluation">
              进入实验验证 ↓
            </a>
          </div>
          <p>
            {created.name} ·{" "}
            {created.synthetic ? "合成数据实验" : created.source}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>日均成交量</th>
                  <th>中位日振幅</th>
                  <th>趋势效率</th>
                  <th>匹配策略</th>
                </tr>
              </thead>
              <tbody>
                {created.profiles.map((p) => (
                  <tr key={p.symbol}>
                    <td>{p.symbol}</td>
                    <td>
                      {Math.round(p.average_daily_volume).toLocaleString()}
                    </td>
                    <td>{p.median_range_pct.toFixed(2)}%</td>
                    <td>{p.trend_efficiency.toFixed(3)}</td>
                    <td>{strategyNames[created.strategies[p.symbol]]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            以上匹配仅依据开发期特征生成研究假设，尚未证明策略有效。
          </p>
        </section>
      )}
      <div id="evaluation">
        <ExperimentRunner selectedId={created?.id} />
      </div>
      </div>
      <div id="position" hidden={horizonType !== "long"}>
        <PositionPanel datasets={datasets} modelEnabled={longEnabled}
          selectedDatasetId={currentLongId} onDatasetChange={setLongDatasetId} />
      </div>
    </>
  );
}
