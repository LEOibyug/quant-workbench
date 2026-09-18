import type { PortfolioPoint, PortfolioTrade } from "./PortfolioCharts";
import { useEffect, useMemo, useState } from "react";
import { DownloadButton } from "./ProgressNotice";
import type { SimulationJob } from "./SimulationPanel";

export interface MarketPoint {
  timestamp: string;
  close: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  shares: number;
  cash: number;
  equity: number;
  benchmark: number;
  drawdown_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  position_id: string | null;
  fees: number;
  impact_cost: number;
  probability: number | null;
  expected_return_bps: number | null;
  required_edge_bps: number | null;
  rule_candidate?: boolean;
  rule_reason?: string | null;
  model_risk_fraction?: number | null;
  model_allow_entry?: boolean | null;
  decision_reason?: string | null;
}
interface Fill {
  timestamp: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  impact_cost: number;
  realized_pnl: number | null;
  position_id: string;
  reason: string;
}
export interface SimulationData {
  portfolio_enabled?: boolean;
  portfolio_curve?: PortfolioPoint[];
  portfolio_trades?: PortfolioTrade[];
  market_curve: MarketPoint[];
  trades: Fill[];
  metrics?: Record<string, number | null>;
  assumptions?: string[];
  model_statistics?: Record<string, unknown>;
  decision_funnel?: Record<string, unknown>;
}
interface Series {
  key: keyof MarketPoint;
  label: string;
  color: string;
}
const money = (n: number) =>
  n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const stamp = (s: string) =>
  new Date(s).toLocaleString("zh-CN", {
    timeZone: "America/New_York",
    hour12: false,
  });
const colors = {
  blue: "#397bd5",
  green: "#168060",
  red: "#c95353",
  gold: "#b17a10",
  purple: "#805cbe",
};

function LineChart({
  title,
  unit,
  points,
  series,
  trades = [],
  selected,
  onSelect,
  current,
}: {
  title: string;
  unit: string;
  points: MarketPoint[];
  series: Series[];
  trades?: Fill[];
  selected: number | null;
  onSelect: (i: number | null) => void;
  current: MarketPoint;
}) {
  const [chosen, setChosen] = useState<Fill | null>(null);
  const geometry = useMemo(() => {
    const indices = new Set<number>([0, points.length - 1]);
    const stride = Math.max(1, Math.ceil(points.length / 700));
    for (let i = 0; i < points.length; i += stride) {
      for (const s of series) {
        let low = i,
          high = i;
        for (let j = i; j < Math.min(i + stride, points.length); j++) {
          if (
            points[j][s.key] !== null &&
            Number(points[j][s.key]) < Number(points[low][s.key] ?? Infinity)
          )
            low = j;
          if (
            points[j][s.key] !== null &&
            Number(points[j][s.key]) > Number(points[high][s.key] ?? -Infinity)
          )
            high = j;
        }
        indices.add(low);
        indices.add(high);
      }
    }
    const samples = [...indices].sort((a, b) => a - b);
    const values = samples
      .flatMap((i) => series.map((s) => points[i][s.key]))
      .filter((v) => typeof v === "number" && Number.isFinite(v)) as number[];
    // Include execution prices so price markers remain inside the chart.
    values.push(...trades.map((t) => t.price));
    let low = values.length ? Math.min(...values) : 0,
      high = values.length ? Math.max(...values) : 1;
    const margin = (high - low || Math.abs(high) * 0.01 || 1) * 0.12;
    low -= margin;
    high += margin;
    return { samples, low, high };
  }, [points, series, trades]);
  const x = (i: number) => 78 + (i / Math.max(1, points.length - 1)) * 854;
  const y = (v: number) =>
    195 - ((v - geometry.low) / (geometry.high - geometry.low)) * 169;
  const indexFor = (ts: string) => {
    const time = Math.ceil(new Date(ts).getTime() / 60000) * 60000;
    let lo = 0,
      hi = points.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (new Date(points[mid].timestamp).getTime() < time) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  };
  const roundTrips = useMemo(() => {
    const byPosition = new Map<string, Fill[]>();
    for (const t of trades)
      byPosition.set(t.position_id, [...(byPosition.get(t.position_id) || []), t]);
    return [...byPosition.values()]
      .map((group) => {
        const buy = group.find((t) => t.side === "buy");
        const sells = group.filter((t) => t.side === "sell");
        const last = sells[sells.length - 1];
        if (!buy || !last) return null;
        const pnl = sells.reduce((sum, t) => sum + (t.realized_pnl || 0), 0);
        return { buy, last, pnl };
      })
      .filter(Boolean)
      .slice(-120) as { buy: Fill; last: Fill; pnl: number }[];
  }, [trades]);
  const at =
    selected === null ? current : points[Math.min(selected, points.length - 1)];
  const activeTrade = chosen
    ? trades.find(
        (t) =>
          t.timestamp === chosen.timestamp &&
          t.position_id === chosen.position_id &&
          t.side === chosen.side,
      )
    : null;
  const pnlForEntry = (trade: Fill) =>
    trades
      .filter((t) => t.position_id === trade.position_id && t.side === "sell")
      .reduce((sum, t) => sum + (t.realized_pnl || 0), 0) +
    (current.position_id === trade.position_id ? current.unrealized_pnl : 0);
  return (
    <section className="card simulation-chart">
      <div className="chart-title">
        <h3>{title}</h3>
        <span className="muted">{unit}</span>
      </div>
      <div className="chart-legend">
        {series.map((s) => (
          <span key={s.key} style={{ color: s.color }}>
            {s.label} {at[s.key] === null ? "—" : money(Number(at[s.key]))}
          </span>
        ))}
      </div>
      <div className="chart-scroll">
        <svg
          viewBox="0 0 960 235"
          role="img"
          aria-label={title}
          onPointerMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const fraction = Math.min(
              1,
              Math.max(
                0,
                (((e.clientX - rect.left) / rect.width) * 960 - 78) / 854,
              ),
            );
            onSelect(Math.round(fraction * (points.length - 1)));
          }}
          onPointerLeave={() => onSelect(null)}
        >
          {[0, 1, 2, 3].map((i) => {
            const value =
              geometry.low + ((geometry.high - geometry.low) * i) / 3;
            return (
              <g key={i}>
                <line
                  x1="78"
                  x2="932"
                  y1={y(value)}
                  y2={y(value)}
                  stroke="#e4e9ef"
                />
                <text x="70" y={y(value) + 4} textAnchor="end">
                  {value.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                </text>
              </g>
            );
          })}
          {series.map((s) => {
            let connected = false;
            const path = geometry.samples
              .map((i) => {
                const v = points[i][s.key];
                if (v === null || !Number.isFinite(Number(v))) {
                  connected = false;
                  return "";
                }
                const command = connected ? "L" : "M";
                connected = true;
                return `${command}${x(i).toFixed(1)},${y(Number(v)).toFixed(1)}`;
              })
              .join(" ");
            return (
              <path
                key={s.key}
                d={path}
                stroke={s.color}
                fill="none"
                strokeWidth="1.8"
              />
            );
          })}
          {roundTrips.map((rt, i) => {
            const x1 = x(indexFor(rt.buy.timestamp)),
              x2 = x(indexFor(rt.last.timestamp));
            if (x2 - x1 < 2) return null;
            return (
              <line
                key={`rt-${i}`}
                className="trade-link"
                x1={x1}
                x2={x2}
                y1={y(rt.buy.price)}
                y2={y(rt.last.price)}
                stroke={rt.pnl >= 0 ? colors.green : colors.red}
                strokeWidth="1.4"
                strokeDasharray="5 4"
                opacity="0.75"
              />
            );
          })}
          {trades.slice(-400).map((t, i) => {
            const lo = indexFor(t.timestamp),
              px = x(lo),
              py = y(t.price),
              buy = t.side === "buy";
            const label = `${buy ? "买入" : "卖出"} ${stamp(t.timestamp)} · ${t.quantity}股 @ $${money(t.price)} · 费用 $${money(t.fee)} · ${buy ? "此笔截至回放时刻净盈亏" : "本次卖出净盈亏"} $${money(buy ? pnlForEntry(t) : t.realized_pnl || 0)}`;
            return (
              <g
                key={`${t.timestamp}-${i}`}
                className="trade-marker"
                tabIndex={0}
                role="button"
                aria-label={label}
                onClick={() => setChosen(t)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setChosen(t);
                  }
                }}
              >
                <title>{label}</title>
                <line
                  x1={px}
                  x2={px}
                  y1={py}
                  y2={py + (buy ? 16 : -16)}
                  stroke={buy ? colors.green : colors.red}
                  strokeWidth="2"
                />
                <circle
                  cx={px}
                  cy={py}
                  r="3"
                  fill={buy ? colors.green : colors.red}
                />
                <circle
                  cx={px}
                  cy={py + (buy ? 16 : -16)}
                  r="10"
                  fill={buy ? colors.green : colors.red}
                  stroke="white"
                  strokeWidth="1.5"
                />

              </g>
            );
          })}
          {selected !== null && (
            <line
              x1={x(selected)}
              x2={x(selected)}
              y1="20"
              y2="198"
              stroke="#8696a7"
              strokeDasharray="4 4"
            />
          )}
          <text x="78" y="222">
            {stamp(points[0].timestamp)}
          </text>
          <text x="932" y="222" textAnchor="end">
            {stamp(current.timestamp)}
          </text>
        </svg>
      </div>
      <small className="muted">
        {stamp(at.timestamp)} 美东时间 · 按交易分钟连续排列，跳过休市
        {points.length > 700 ? " · 长区间保留极值抽样绘图" : ""}
      </small>
      {trades.length > 0 && (
        <p className="muted">
          绿色圆点为买入、红色圆点为卖出，虚线连接同一持仓的买入与最后一次卖出（绿盈红亏）·
          点击标记查看成交与盈亏
          {trades.length > 400 ? "（图中显示最近 400 次成交）" : ""}
        </p>
      )}
      {activeTrade && (
        <p className="trade-detail">
          <span className={activeTrade.side === "buy" ? "side-buy" : "side-sell"}>
            {activeTrade.side === "buy" ? "买入" : "卖出"}
          </span>{" "}
          · {stamp(activeTrade.timestamp)} · {activeTrade.quantity} 股 @ $
          {money(activeTrade.price)} · 费用 ${money(activeTrade.fee)} ·{" "}
          {activeTrade.side === "buy"
            ? "此笔截至回放时刻净盈亏（含浮盈亏）"
            : "此次卖出净盈亏"}{" "}
          <span
            className={
              (activeTrade.side === "buy"
                ? pnlForEntry(activeTrade)
                : activeTrade.realized_pnl || 0) >= 0
                ? "pos"
                : "neg"
            }
          >
            $
            {money(
              activeTrade.side === "buy"
                ? pnlForEntry(activeTrade)
                : activeTrade.realized_pnl || 0,
            )}
          </span>
        </p>
      )}
    </section>
  );
}
const priceSeries: Series[] = [
  { key: "close", label: "收盘价", color: colors.blue },
];
const equitySeries: Series[] = [
  { key: "equity", label: "净资产", color: colors.green },
  { key: "benchmark", label: "日内无成本持有基准", color: "#8994a5" },
];
const pnlSeries: Series[] = [
  { key: "realized_pnl", label: "累计已实现", color: colors.blue },
  { key: "unrealized_pnl", label: "当前浮动", color: colors.gold },
];
const ddSeries: Series[] = [
  { key: "drawdown_pct", label: "回撤", color: colors.red },
];
const positionSeries: Series[] = [
  { key: "shares", label: "持仓股数", color: colors.purple },
];
const probabilitySeries: Series[] = [
  { key: "probability", label: "上涨概率（0—1）", color: colors.purple },
];
const edgeSeries: Series[] = [
  { key: "expected_return_bps", label: "预测收益", color: colors.blue },
  { key: "required_edge_bps", label: "成本过滤门槛", color: colors.gold },
];

export function SimulationCharts({
  data,
  job,
  exportBase,
}: {
  data: SimulationData;
  job: SimulationJob;
  exportBase: string;
}) {
  const [cursor, setCursor] = useState(data.market_curve.length),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(30);
  const [follow, setFollow] = useState(true),
    [hover, setHover] = useState<number | null>(null);
  const count = data.market_curve.length;
  const shown = Math.min(count, Math.max(1, follow ? count : cursor));
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(
      () =>
        setCursor((prev) => {
          const next = Math.min(
            count,
            prev + Math.max(1, Math.round(speed / 5)),
          );
          return next;
        }),
      200,
    );
    return () => clearInterval(timer);
  }, [playing, count, speed]);
  useEffect(() => {
    if (playing && cursor >= count) setPlaying(false);
  }, [cursor, count, playing]);
  const points = useMemo(
    () => data.market_curve.slice(0, shown),
    [data.market_curve, shown],
  );
  const current = points[points.length - 1];
  const trades = useMemo(
    () => data.trades.filter((t) => t.timestamp <= current.timestamp),
    [data.trades, current.timestamp],
  );
  const completed = job.status === "completed" && shown === count;
  const daily = useMemo(() => {
    const days = new Map<string, number>();
    for (const p of points) days.set(p.timestamp.slice(0, 10), p.equity);
    let prev = job.initial_cash;
    return [...days].map(([date, value]) => {
      const pct = (value / prev - 1) * 100;
      prev = value;
      return { date, pct };
    });
  }, [points, job.initial_cash]);
  const chartProps = {
    points,
    selected: hover === null ? null : Math.min(hover, shown - 1),
    onSelect: setHover,
    current,
  };
  const buys = trades.filter((t) => t.side === "buy").length;
  const sells = trades.length - buys;
  const hasDiagnostics = points.some(
    (p) => typeof p.rule_candidate === "boolean",
  );
  const candidates = points.filter((p) => p.rule_candidate);
  const blocked = candidates.filter((p) => p.model_allow_entry === false);
  const oldCostVetoes = completed
    ? Number(data.model_statistics?.cost_vetoes || 0)
    : 0;
  function seekTrade(first = false) {
    const next = first
      ? data.trades[0]
      : data.trades.find((t) => t.timestamp > current.timestamp);
    if (!next) return;
    const index = data.market_curve.findIndex(
      (p) => p.timestamp >= next.timestamp,
    );
    if (index >= 0) {
      setFollow(false);
      setPlaying(false);
      setCursor(index + 1);
      setHover(null);
    }
  }
  const dailyMax = Math.max(0.01, ...daily.map((d) => Math.abs(d.pct)));
  const net = current.equity - job.initial_cash;
  const metrics: [string, string, string?][] = [
    ["股票价格", `$${money(current.close)}`],
    ["净资产", `$${money(current.equity)}`],
    [
      "累计净收益",
      `${net >= 0 ? "+" : "-"}$${money(Math.abs(net))} (${money((current.equity / job.initial_cash - 1) * 100)}%)`,
      net >= 0 ? "pos" : "neg",
    ],
    ["可用现金", `$${money(current.cash)}`],
    [
      "已实现 / 浮动盈亏",
      `$${money(current.realized_pnl)} / $${money(current.unrealized_pnl)}`,
      current.realized_pnl + current.unrealized_pnl >= 0 ? "pos" : "neg",
    ],
    [
      "持仓",
      `${current.shares} 股${current.shares === 0 && trades.length ? "（已清仓）" : ""}`,
    ],
    ["累计成交", `${trades.length} 次 · 买 ${buys} / 卖 ${sells}`],
    ["累计佣金与规费", `$${money(current.fees)}`],
    ["价差与滑点成本（已含成交价）", `$${money(current.impact_cost)}`],
  ];
  return (
    <>
      <section className="card replay-controls">
        <div className="simulation-status">
          <h3>
            {job.symbol} · {stamp(current.timestamp)} <small>美东</small>
          </h3>
          <span className="badge">
            {playing
              ? "历史回放中"
              : follow && job.status === "running"
                ? "跟随计算进度"
                : completed
                  ? "回放结束"
                  : "已暂停"}
          </span>
        </div>
        <div className="replay-buttons">
          <button
            onClick={() => {
              setFollow(false);
              if (shown >= count) setCursor(1);
              else setCursor(shown);
              setPlaying(!playing);
            }}
          >
            {playing ? "暂停" : "播放"}
          </button>
          <button
            onClick={() => {
              setFollow(false);
              setPlaying(false);
              setCursor(1);
            }}
          >
            回到起点
          </button>
          <button
            onClick={() => {
              setFollow(true);
              setPlaying(false);
            }}
          >
            显示已计算全部
          </button>
          <button onClick={() => seekTrade(true)}>定位首笔成交</button>
          <button onClick={() => seekTrade()}>下一笔成交</button>
          <label>
            回放速度
            <select
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            >
              {[5, 30, 120, 600].map((n) => (
                <option key={n} value={n}>
                  {n} 分钟/秒
                </option>
              ))}
            </select>
          </label>
        </div>
        <input
          aria-label="模拟回放时间"
          type="range"
          min="1"
          max={count}
          value={shown}
          onChange={(e) => {
            setFollow(false);
            setPlaying(false);
            setCursor(Number(e.target.value));
            setHover(null);
          }}
        />
        <small>
          {shown.toLocaleString()} / {count.toLocaleString()}{" "}
          个已计算分钟。图表、盈亏与成交列表仅展示回放时刻之前的信息。
        </small>
      </section>
      <section className="card trading-summary" role="status">
        <h3>
          {completed ? "模拟结果" : "截至当前回放时刻"} · 买入 {buys} 次 / 卖出{" "}
          {sells} 次
        </h3>
        {!trades.length ? (
          <>
            <p>
              尚无成交，因此没有买卖点；净资产仍为初始资金，收益、费用、持仓为
              0。行情曲线显示的是股票价格变化，并不表示策略已买入。
            </p>
            {hasDiagnostics && (
              <p>
                规则入场候选 {candidates.length} 个分钟，其中模型未放行{" "}
                {blocked.length} 个分钟。
                {candidates.length === 0
                  ? "当前区间尚未满足规则入场条件。"
                  : "放行后还需在下一分钟满足资金和成交量约束才会成交。"}
              </p>
            )}
            {oldCostVetoes > 0 && (
              <p>
                模型统计：{oldCostVetoes}{" "}
                个分钟周期未通过预期收益覆盖成本的条件（模型评估次数，不等于被拒订单数）。
              </p>
            )}
          </>
        ) : (
          <p>
            买卖点已绘于下方价格图；可点击标记查看成交价、费用及对应净盈亏。
            {current.shares === 0
              ? `当前已经清仓，持仓和浮动盈亏为 0；累计已实现净盈亏为 $${money(current.realized_pnl)}，不会因清仓清零。`
              : `当前持仓 ${current.shares} 股，浮动盈亏为 $${money(current.unrealized_pnl)}。`}
          </p>
        )}
        {current.decision_reason && (
          <p className="muted">当前模型判断：{current.decision_reason}</p>
        )}
        {current.rule_reason && (
          <p className="muted">
            当前规则状态：{current.rule_reason}
            {current.model_risk_fraction != null
              ? ` · 模型风险预算比例 ${(current.model_risk_fraction * 100).toFixed(0)}%`
              : ""}
          </p>
        )}
        {completed && data.decision_funnel && (
          <details>
            <summary>入场机会与拦截统计</summary>
            <pre>{JSON.stringify(data.decision_funnel, null, 2)}</pre>
          </details>
        )}
        {completed && (
          <p>
            最终净资产 ${money(current.equity)} · 累计净收益 $
            {money(current.equity - job.initial_cash)} · 胜率{" "}
            {data.metrics?.win_rate_pct == null
              ? "不适用（无完整往返交易）"
              : `${money(data.metrics.win_rate_pct)}%`}{" "}
            · 日收益 Sharpe{" "}
            {data.metrics?.daily_sharpe == null
              ? "不适用（交易日不足或收益无波动）"
              : money(data.metrics.daily_sharpe)}
          </p>
        )}
      </section>
      <div className="simulation-metrics">
        {metrics.map(([label, value, tone]) => (
          <div className="card" key={label}>
            <small>{label}</small>
            <strong className={tone || ""}>{value}</strong>
          </div>
        ))}
      </div>
      <LineChart
        title="股票走势与买卖点"
        unit="USD / 股"
        series={priceSeries}
        trades={trades}
        {...chartProps}
      />
      <LineChart
        title="资金曲线"
        unit="USD"
        series={equitySeries}
        {...chartProps}
      />
      <div className="simulation-grid">
        <LineChart
          title="已实现与浮动盈亏"
          unit="USD · 扣除成本"
          series={pnlSeries}
          {...chartProps}
        />
        <LineChart
          title="资金回撤"
          unit="%"
          series={ddSeries}
          {...chartProps}
        />
        <LineChart
          title="持仓变化"
          unit="股"
          series={positionSeries}
          {...chartProps}
        />
        <section className="card simulation-chart">
          <h3>逐日收益</h3>
          <p className="muted">截至回放时刻；当日尚未收盘时为当日累计值。</p>
          <svg viewBox="0 0 500 220" role="img" aria-label="逐日收益柱状图">
            <line x1="30" x2="480" y1="100" y2="100" stroke="#aab4c1" />
            {daily.map((d, i) => (
              <g key={d.date}>
                <rect
                  x={30 + (i * 450) / daily.length}
                  y={d.pct >= 0 ? 100 - (d.pct / dailyMax) * 80 : 100}
                  width={Math.max(1, 450 / daily.length - 2)}
                  height={Math.max(1, (Math.abs(d.pct) / dailyMax) * 80)}
                  fill={d.pct >= 0 ? colors.green : colors.red}
                >
                  <title>
                    {d.date}: {money(d.pct)}%
                  </title>
                </rect>
              </g>
            ))}
            <text x="30" y="203">
              {daily[0]?.date}
            </text>
            <text x="480" y="203" textAnchor="end">
              {daily[daily.length - 1]?.date}
            </text>
            <text x="30" y="14">
              ±{money(dailyMax)}%
            </text>
          </svg>
        </section>
      </div>
      {points.some((p) => p.probability !== null) && (
        <div className="simulation-grid">
          <LineChart
            title="时序模型预测"
            unit="概率"
            series={probabilitySeries}
            {...chartProps}
          />
          <LineChart
            title="预测收益与成本门槛"
            unit="bps"
            series={edgeSeries}
            {...chartProps}
          />
        </div>
      )}
      <section className="card">
        <h3>成交明细与对应盈亏</h3>
        <p className="muted">
          当前已发生 {trades.length} 次成交，展示最近 300
          次。卖出盈亏按对应买入成本（含佣金）分摊；价差与滑点已经体现在成交价内。
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间（美东）</th>
                <th>方向 / 持仓编号</th>
                <th>股数</th>
                <th>成交价</th>
                <th>费用</th>
                <th>已实现净盈亏</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              {trades
                .slice(-300)
                .reverse()
                .map((t, i) => (
                  <tr key={`${t.timestamp}-${i}`}>
                    <td>{stamp(t.timestamp)}</td>
                    <td className={t.side === "buy" ? "side-buy" : "side-sell"}>
                      {t.side === "buy" ? "买入" : "卖出"}
                      {t.position_id ? ` · ${t.position_id}` : ""}
                    </td>
                    <td>{t.quantity}</td>
                    <td>${money(t.price)}</td>
                    <td>${money(t.fee)}</td>
                    <td>
                      {t.realized_pnl === null ? (
                        <span className="muted">待卖出</span>
                      ) : (
                        <span className={t.realized_pnl >= 0 ? "pos" : "neg"}>
                          {t.realized_pnl >= 0 ? "+" : "-"}$
                          {money(Math.abs(t.realized_pnl))}
                        </span>
                      )}
                    </td>
                    <td>{t.reason}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        {!trades.length && (
          <p className="notice">
            截至当前时刻没有成交。价格与预测仍会更新；资金保持不变是有效模拟结果。
          </p>
        )}
        {completed && (
          <>
            <div className="replay-buttons">
              <DownloadButton href={`${exportBase}/trades`}>
                导出全部成交 CSV
              </DownloadButton>
              <DownloadButton href={`${exportBase}/market_curve`}>
                导出分钟曲线 CSV
              </DownloadButton>
              <DownloadButton href={`${exportBase}/daily_returns`}>
                导出日收益 CSV
              </DownloadButton>
            </div>
            <details>
              <summary>完整模拟指标与假设</summary>
              <pre>{JSON.stringify(data.metrics, null, 2)}</pre>
              {data.assumptions?.map((a) => (
                <p key={a}>{a}</p>
              ))}
            </details>
          </>
        )}
      </section>
    </>
  );
}
