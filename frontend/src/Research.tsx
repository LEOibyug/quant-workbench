import { useEffect, useState } from "react";
import { ExperimentRunner } from "./ExperimentRunner";
import { api, post } from "./api";
import { strategyNames } from "./types";
import type { Dataset, Experiment } from "./types";
const tomorrow = (day: string) =>
  new Date(Date.parse(day) + 86400000).toISOString().slice(0, 10);
export function Research() {
  const [datasets, setDatasets] = useState<Dataset[]>([]),
    [selected, setSelected] = useState("");
  const [symbols, setSymbols] = useState<string[]>([]),
    [dates, setDates] = useState(["", "", "", ""]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [created, setCreated] = useState<Experiment | null>(null);
  const [provider, setProvider] = useState("alpaca");
  const [providers, setProviders] = useState<
    { id: string; name: string; configured: boolean; note: string }[]
  >([]);
  const [enabled, setEnabled] = useState(true);
  const dataset = datasets.find((d) => d.id === selected);
  const choose = (d: Dataset) => {
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
  async function loadData(work: () => Promise<Dataset>) {
    setBusy(true);
    setError("");
    try {
      const d = await work();
      setDatasets((prev) => [d, ...prev.filter((x) => x.id !== d.id)]);
      choose(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    const n = (key: string) => Number(f.get(key));
    try {
      const result = await post<Experiment>("/experiments", {
        name: f.get("name"),
        dataset_id: selected,
        symbols,
        start: dates[0],
        train_end: dates[1],
        validation_end: dates[2],
        end: dates[3],
        config: {
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
        },
        model: enabled
          ? {
              enabled: true,
              k: n("k"),
              horizon: n("horizon"),
              architecture: f.get("architecture"),
              probability_threshold: n("threshold"),
              online_learning_rate: n("learning_rate"),
              cost_aware: f.get("cost_aware") === "on",
              cost_multiplier: n("cost_multiplier"),
              min_edge_bps: n("min_edge"),
            }
          : { enabled: false },
      });
      setCreated(result);
    } catch (e) {
      setError((e as Error).message);
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
          <p>先冻结开发范围、策略与成本，再依次验证。所有运算在本地完成。</p>
        </div>
        <span className="badge">1 MIN · LONG ONLY</span>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <section className="card">
        <div className="section-heading">
          <h2>01 / 行情数据</h2>
          <button
            disabled={busy}
            onClick={() => loadData(() => post<Dataset>("/datasets/demo"))}
          >
            使用合成示例
          </button>
        </div>
        <p className="muted">
          通过数据提供商 API
          直接下载到本地。示例只用于检查流程，不代表真实股票表现。
        </p>
        <div className="form-grid">
          <label>
            本地数据集
            <select
              value={selected}
              onChange={(e) => {
                const d = datasets.find((x) => x.id === e.target.value);
                if (d) choose(d);
              }}
            >
              <option value="">选择数据集</option>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
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
            密钥在本地后端配置。下载后存为可复现快照，研究时直接选择该数据集。当前不自动补齐缺失分钟。
          </p>
          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              loadData(() =>
                post<Dataset>("/datasets/fetch", {
                  provider,
                  symbols: String(f.get("symbols"))
                    .split(",")
                    .map((x) => x.trim().toUpperCase()),
                  start: f.get("start"),
                  end: f.get("end"),
                  feed: f.get("feed") || "iex",
                }),
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
            <label>
              股票代码
              <input
                name="symbols"
                defaultValue="NVDA,TSLA,AAPL,AMD,SOFI"
                required
              />
            </label>
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
            <button disabled={busy}>通过 API 下载</button>
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
        {dataset && (
          <div className="notice">
            {dataset.synthetic ? "合成数据" : dataset.source} ·{" "}
            {dataset.rows.toLocaleString()} 条 · {dataset.start} — {dataset.end}
          </div>
        )}
      </section>
      {dataset && (
        <form onSubmit={create}>
          <section className="card">
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
                <select name="strategy" defaultValue="trend_breakout">
                  {Object.entries(strategyNames).map(([k, v]) => (
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
                  defaultValue={5}
                  min={2}
                  max={60}
                />
              </label>
              <label>
                慢均线周期
                <input
                  name="slow"
                  type="number"
                  defaultValue={20}
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
                <input name="reversion" type="number" defaultValue={30} />
              </label>
            </div>
            <details open>
              <summary>增强策略风控（趋势过滤突破 / 止跌确认回归）</summary>
              <p className="muted">参考过去20个交易日的波动背景，使用已结束分钟确认信号。每天最多4次入场，日亏损1%后停止入场；风险预算不保证限制跳空损失。</p>
              <div className="form-grid">
                <label>最长持仓 分钟<input name="max_hold" type="number" min={5} max={120} defaultValue={30} /></label>
                <label>平仓后冷却 分钟<input name="cooldown" type="number" min={0} max={60} defaultValue={10} /></label>
                <label>止损 ATR倍数<input name="stop_atr" type="number" min={0.5} max={5} step={0.1} defaultValue={2} /></label>
                <label>止盈 ATR倍数<input name="take_atr" type="number" min={1} max={10} step={0.1} defaultValue={3} /></label>
                <label>单笔风险预算 bps<input name="risk_budget" type="number" min={1} max={100} defaultValue={25} /></label>
                <label>规则目标 / 成本倍数<input name="rule_cost" type="number" min={1} max={5} step={0.1} defaultValue={1.5} /></label>
              </div>
            </details>
            <details open>
              <summary>交易成本与成交限制</summary>
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
                    step="0.001"
                    defaultValue={0.005}
                  />
                </label>
                <label>
                  最低佣金 USD/笔
                  <input
                    name="minimum"
                    type="number"
                    step="0.1"
                    defaultValue={1}
                  />
                </label>
                <label>
                  卖出规费 bps
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
          <section className="card">
            <div className="section-heading">
              <h2>03 / 在线时序模型</h2>
              <label className="inline">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                共同决定入场
              </label>
            </div>
            <p>
              模型综合过去 k 根分钟线与约1/5/20交易日的历史背景，输出指定跨度的上涨概率与收益。首 k
              根积累窗口，k—2k 为适应期，前 2k
              根不参与交易；标签在预测跨度到期后才用于更新。MLP同时接收最近已成熟预测、真实值和误差。
            </p>
            {enabled && (
              <div className="form-grid">
                <label>
                  模型结构
                  <select name="architecture" defaultValue="mlp">
                    <option value="mlp">双头 MLP · 64→32 · 误差反馈</option>
                    <option value="rbf">RBF非线性 + 在线双头</option>
                    <option value="linear">线性双头基线</option>
                  </select>
                </label>
                <label>
                  预测跨度 分钟
                  <select name="horizon" defaultValue="5">
                    <option value="1">1</option><option value="5">5</option><option value="15">15</option>
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
                  上涨概率门槛
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
                  预期收益必须覆盖成本
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
                  在线学习率
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
            <p className="muted">
              MLP采用两个64→32隐藏层网络，分别输出概率与收益；线性/RBF版本使用逻辑分类与Huber回归。每股独立更新；跨日保留模型权重和历史背景，重建短窗口与误差反馈，不生成隔夜标签。上涨概率不等同于净盈利概率。成本过滤要求：预测收益
              bps 大于估计往返成本 × 安全倍数 + 最低额外优势。
            </p>
            <button className="primary" disabled={busy || !symbols.length}>
              {busy ? "正在处理…" : "训练并冻结实验"}
            </button>
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
    </>
  );
}
