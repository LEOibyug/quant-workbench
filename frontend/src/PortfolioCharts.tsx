import { useEffect, useId, useMemo, useState } from "react";
import { strategyNames } from "./types";
import { DownloadButton } from "./ProgressNotice";

export interface PortfolioAsset {
  open: number; high: number; low: number; close: number; volume: number; shares: number;
  market_value: number; weight: number; target_weight: number; realized_pnl: number;
  unrealized_pnl: number; fees: number; impact_cost: number;
  forecast?: Record<string, number | string | boolean | null> | null;
}
export interface PortfolioPoint {
  date?: string; timestamp?: string; equity: number; cash: number; cash_weight: number;
  drawdown_pct: number; realized_pnl: number; unrealized_pnl: number; fees: number;
  impact_cost: number; benchmark?: number; assets: Record<string, PortfolioAsset>;
}
export interface PortfolioTrade {
  date?: string; timestamp?: string; symbol: string; side: string; quantity: number;
  price: number; fee: number; impact_cost?: number; realized_pnl?: number | null;
  position_after: number; reason: string;
}
const palette = ["#147d72", "#397bd5", "#9a63b8", "#bb861b", "#e17654", "#52918a", "#724d91", "#ae647e", "#386a9a", "#637d32"];
const profitColor = "#d04b4b", lossColor = "#148565";
const pnlColor = (value: number) => value > 0 ? profitColor : value < 0 ? lossColor : undefined;
function Pnl({ value, percent }: { value: number; percent?: number }) {
  return <span style={{ color: pnlColor(value) }}>${amount(value)}{percent == null ? "" : ` (${amount(percent)}%)`}</span>;
}
const buyColor = "#148565", sellColor = "#d04b4b";
const amount = (v: number | undefined) => (v ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const stamp = (p: { date?: string; timestamp?: string }) => p.timestamp || p.date || "";
const label = (t: string) => t.length <= 10 ? t : new Date(t).toLocaleString("zh-CN", { timeZone: "America/New_York", hour12: false });
const sample = <T,>(items: T[], max = 1000) => items.filter((_, i) => i % Math.max(1, Math.ceil(items.length / max)) === 0 || i === items.length - 1);
function PriceLine({ title, points, value, trades = [], secondary, pnl = false, onTrade, seek }: {
  title: string; points: PortfolioPoint[]; value: (p: PortfolioPoint) => number;
  secondary?: (p: PortfolioPoint) => number; trades?: PortfolioTrade[]; pnl?: boolean;
  onTrade: (t: PortfolioTrade) => void; seek: (index: number) => void;
}) {
  const clipId = useId().replace(/:/g, "");
  const plotted = sample(points);
  const values = plotted.flatMap((p) => secondary ? [value(p), secondary(p)] : [value(p)]).concat(trades.slice(-500).map((t) => t.price), pnl ? [0] : []);
  const low = Math.min(...values), high = Math.max(...values), pad = Math.max((high - low) * .08, Math.abs(high) * .0001, .01);
  const y = (v: number) => 155 - (v - low + pad) / (high - low + pad * 2) * 130;
  const x = (index: number) => 65 + index / Math.max(points.length - 1, 1) * 780;
  const indices = new Map(points.map((p, i) => [stamp(p), i]));
  const line = (fn: (p: PortfolioPoint) => number) => plotted.map((p) => `${x(indices.get(stamp(p)) || 0)},${y(fn(p))}`).join(" ");
  function tradeIndex(time: string) {
    let lo = 0, hi = points.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (stamp(points[mid]) < time) lo = mid + 1; else hi = mid; }
    return lo;
  }
  return <section className="portfolio-chart">
    <h3>{title}</h3>
    <svg viewBox="0 0 900 195" role="img" aria-label={title} onClick={(e) => {
      const box = e.currentTarget.getBoundingClientRect();
      seek(Math.max(0, Math.min(points.length - 1, Math.round(((e.clientX - box.left) / box.width * 900 - 65) / 780 * (points.length - 1)))));
    }}>
      <text x="5" y="25">{amount(high)}</text><text x="5" y="155">{amount(low)}</text>
      <line x1="65" x2="845" y1="160" y2="160" stroke="#cbd5dc" />
      {secondary && <polyline fill="none" stroke="#9ca8b2" strokeWidth="1.5" strokeDasharray="5 3" points={line(secondary)} />}
      {pnl && values.some((v) => v !== 0) ? <>
        <defs>
          <clipPath id={`${clipId}-profit`}><rect width="900" height={y(0)} /></clipPath>
          <clipPath id={`${clipId}-loss`}><rect y={y(0)} width="900" height={195-y(0)} /></clipPath>
        </defs>
        <line x1="65" x2="845" y1={y(0)} y2={y(0)} stroke="#9ca8b2" strokeDasharray="4 3" />
        <polyline fill="none" stroke={profitColor} strokeWidth="1.8" points={line(value)} clipPath={`url(#${clipId}-profit)`} />
        <polyline fill="none" stroke={lossColor} strokeWidth="1.8" points={line(value)} clipPath={`url(#${clipId}-loss)`} />
      </> : <polyline fill="none" stroke={pnl ? "#8f9ca8" : "#397bd5"} strokeWidth="1.8" points={line(value)} /> }
      {trades.slice(-500).map((t, i) => <path key={i} className="trade-marker" data-side={t.side}
        d="M -2 -17 H 2 V -8 H 6 L 0 0 L -6 -8 H -2 Z"
        transform={`translate(${x(tradeIndex(stamp(t)))},${y(t.price)})`} fill={t.side === "buy" ? buyColor : sellColor}
        stroke="white" strokeWidth="1" tabIndex={0} role="button"
        aria-label={`${t.side.toUpperCase()} ${t.symbol} ${stamp(t)} ${t.quantity} @ ${t.price}`}
        onClick={(e) => { e.stopPropagation(); onTrade(t); }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onTrade(t); } }}>
        <title>{t.side.toUpperCase()} {label(stamp(t))} · {t.quantity} @ ${amount(t.price)}</title>
      </path>)}
      <text x="65" y="184">{label(stamp(points[0]))}</text>
      <text x="845" y="184" textAnchor="end">{label(stamp(points[points.length - 1]))}</text>
    </svg>
  </section>;
}
export function PortfolioCharts({ curve, trades, initialCash, allocationEnabled, curveExport, tradesExport, decisionsExport }: {
  curve: PortfolioPoint[]; trades: PortfolioTrade[]; initialCash: number; allocationEnabled?: boolean;
  curveExport: string; tradesExport: string; decisionsExport?: string;
}) {
  const [cursor, setCursor] = useState(curve.length);
  const [playing, setPlaying] = useState(false), [speed, setSpeed] = useState(5);
  const [chosen, setChosen] = useState<PortfolioTrade | null>(null);
  useEffect(() => { setCursor(curve.length); setPlaying(false); setChosen(null); }, [curve]);
  useEffect(() => {
    const pause = () => setPlaying(false);
    window.addEventListener("quant:pause-replay", pause);
    return () => window.removeEventListener("quant:pause-replay", pause);
  }, []);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setCursor((i) => Math.min(curve.length, i + speed)), 1000);
    return () => clearInterval(timer);
  }, [playing, speed, curve.length]);
  useEffect(() => { if (cursor >= curve.length) setPlaying(false); }, [cursor, curve.length]);
  const shown = Math.min(curve.length, Math.max(1, cursor));
  const points = useMemo(() => curve.slice(0, shown), [curve, shown]);
  const at = points[points.length - 1];
  const visibleTrades = useMemo(() => trades.filter((t) => stamp(t) <= stamp(at)), [trades, at]);
  const symbols = Object.keys(at.assets);
  const seek = (i: number) => { setCursor(i + 1); setPlaying(false); setChosen(null); };
  const daily = useMemo(() => {
    const days = new Map<string, number>();
    points.forEach((p) => days.set(p.date || new Date(p.timestamp!).toLocaleDateString("en-CA", { timeZone: "America/New_York" }), p.equity));
    let before = initialCash;
    return [...days].map(([date, equity]) => { const pct = (equity / before - 1) * 100; before = equity; return { date, pct }; });
  }, [points, initialCash]);
  const dailyMean = daily.reduce((sum, d) => sum + d.pct, 0) / daily.length;
  const dailyStd = daily.length > 1 ? Math.sqrt(daily.reduce((sum, d) => sum + (d.pct - dailyMean) ** 2, 0) / (daily.length - 1)) : 0;
  const sales = visibleTrades.filter((t) => t.side === "sell" && t.realized_pnl != null);
  const allocationPoints = sample(points);
  const dailyMax = Math.max(.01, ...daily.map((r) => Math.abs(r.pct)));
  const shownTrade = chosen && stamp(chosen) <= stamp(at) ? chosen : null;
  const chart = { points, onTrade: setChosen, seek };
  return <div className="portfolio-review">
    <h2>组合详细复盘</h2>
    <div className="replay-buttons">
      <button onClick={() => { if (cursor >= curve.length) setCursor(1); setPlaying(!playing); }}>{playing ? "暂停" : "播放"}</button>
      <button onClick={() => seek(0)}>回到起点</button>
      <button onClick={() => seek(curve.length - 1)}>显示全部</button>
      <button onClick={() => { const t = trades.find((t) => stamp(t) > stamp(at)) || trades[0]; if (t) seek(curve.findIndex((p) => stamp(p) >= stamp(t))); }}>下一笔成交</button>
      <label>回放速度<select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>{[1, 5, 30, 120].map((n) => <option key={n} value={n}>{n} 周期/秒</option>)}</select></label>
    </div>
    <input aria-label="组合回放时间" type="range" min={1} max={curve.length} value={shown} onChange={(e) => seek(Number(e.target.value) - 1)} />
    <p>{label(stamp(at))} · {shown} / {curve.length} {at.date ? "交易日" : "分钟"}。图表与成交只显示至回放时刻；点击曲线可定位。</p>
    <div className="simulation-metrics">
      {[
        ["净资产", `$${amount(at.equity)}`], ["净收益", <Pnl value={at.equity - initialCash} percent={(at.equity / initialCash - 1) * 100} />],
        ["可用现金", `$${amount(at.cash)} (${amount(at.cash_weight * 100)}%)`],
        ["已实现 / 浮动盈亏", <><Pnl value={at.realized_pnl} /> / <Pnl value={at.unrealized_pnl} /></>],
        ["当前回撤", `${amount(at.drawdown_pct)}%`], ["累计成交", `${visibleTrades.length} · 买 ${visibleTrades.filter((t) => t.side === "buy").length} / 卖 ${visibleTrades.filter((t) => t.side === "sell").length}`],
        ["截至当前最大回撤", `${amount(points.reduce((max, p) => Math.max(max, p.drawdown_pct), 0))}%`],
        ["日收益 Sharpe", dailyStd > 1e-10 ? amount(dailyMean / dailyStd * Math.sqrt(252)) : "—"],
        ["卖出成交胜率", sales.length ? `${amount(sales.filter((t) => (t.realized_pnl || 0) > 0).length / sales.length * 100)}%` : "—"],
        ["累计成交额", `$${amount(visibleTrades.reduce((sum, t) => sum + t.quantity * t.price, 0))}`],
        ["佣金与规费", `$${amount(at.fees)}`], ["价差与滑点成本", `$${amount(at.impact_cost)}`],
      ].map(([name, value]) => <div className="card" key={String(name)}><small>{name}</small><strong>{value}</strong></div>)}
    </div>
    <PriceLine title="组合净值 USD" {...chart} value={(p) => p.equity} secondary={at.benchmark == null ? undefined : (p) => p.benchmark!} />
    {at.benchmark != null && <p className="muted">灰色虚线：日内等权无成本持有基准。</p>}
    <div className="simulation-grid">
      <PriceLine title="回撤 %" {...chart} value={(p) => p.drawdown_pct} />
      <PriceLine title="可用现金 USD" {...chart} value={(p) => p.cash} />
      <PriceLine title="已实现盈亏 USD" {...chart} value={(p) => p.realized_pnl} />
      <PriceLine title="浮动盈亏 USD" {...chart} value={(p) => p.unrealized_pnl} />
    </div>
    <h3>股票占比与现金 · {allocationEnabled ? "组合轮换已启用" : "原策略分配"}</h3>
    <div className="chart-legend">{[...symbols, "现金"].map((s, i) => <span key={s} style={{ color: i === symbols.length ? "#8f9ca8" : palette[i % palette.length] }}>{s}</span>)}</div>
    <svg viewBox="0 0 900 195" role="img" aria-label="股票与现金实际占比历史">
      {[...symbols, "现金"].map((s, j) => {
        const bounds = allocationPoints.map((p, i) => {
          const lower = symbols.slice(0, j).reduce((sum, symbol) => sum + (p.assets[symbol]?.weight || 0), 0);
          const weight = j === symbols.length ? p.cash_weight : p.assets[s]?.weight || 0;
          const x = 50 + i / Math.max(1, allocationPoints.length - 1) * 800;
          return { x, lower: 160 - lower * 140, upper: 160 - (lower + weight) * 140 };
        });
        return <polygon key={s} fill={j === symbols.length ? "#aab4be" : palette[j % palette.length]}
          points={[...bounds.map((b) => `${b.x},${b.upper}`), ...[...bounds].reverse().map((b) => `${b.x},${b.lower}`)].join(" ")}><title>{s}</title></polygon>;
      })}
      <text x="0" y="24">100%</text><text x="10" y="162">0%</text>
      <text x="50" y="185">{label(stamp(points[0]))}</text><text x="850" y="185" textAnchor="end">{label(stamp(at))}</text>
    </svg>
    <div className="table-wrap"><table><thead><tr><th>股票</th><th>实际占比</th><th>目标占比</th><th>股数</th><th>市值</th><th>已实现</th><th>浮动盈亏</th><th>费用</th></tr></thead>
      <tbody>{symbols.map((s, i) => { const a = at.assets[s]; return <tr key={s}><td style={{ color: palette[i % palette.length] }}>{s}</td><td>{amount(a.weight * 100)}%</td><td>{amount(a.target_weight * 100)}%</td><td>{a.shares}</td><td>${amount(a.market_value)}</td><td><Pnl value={a.realized_pnl} /></td><td><Pnl value={a.unrealized_pnl} /></td><td>${amount(a.fees)}</td></tr>; })}
      <tr><td>现金</td><td>{amount(at.cash_weight * 100)}%</td><td colSpan={6}>${amount(at.cash)}</td></tr></tbody></table></div>
    <h3>各股价格、成交与持仓</h3>
    <p className="muted"><span style={{ color: buyColor }}>↓</span> 买入 · <span style={{ color: sellColor }}>↓</span> 卖出。蓝线为收盘价，向下箭头尖端为成交价；每股显示截至当前的最近500笔，点击查看详情。</p>
    <p className="muted">单股累计净收益 = 已实现盈亏 + 浮动盈亏，包含成交费用，红盈绿亏；共享资金持续变化，使用 USD 金额展示，不把股价涨幅当作策略收益。</p>
    {shownTrade && <p className="trade-detail"><span style={{ color: shownTrade.side === "buy" ? buyColor : sellColor }}>●</span> {shownTrade.symbol} · {label(stamp(shownTrade))} · {shownTrade.quantity} 股 @ ${amount(shownTrade.price)} · 费用 ${amount(shownTrade.fee)} · 已实现盈亏 {shownTrade.realized_pnl == null ? "—" : <Pnl value={shownTrade.realized_pnl} />}</p>}
    {symbols.map((s) => <div key={s}>
      <PriceLine title={`${s} · 价格与买卖点 USD`} {...chart} value={(p) => p.assets[s].close} trades={visibleTrades.filter((t) => t.symbol === s)} />
      <PriceLine title={`${s} · 累计净收益 USD`} {...chart} pnl value={(p) => p.assets[s].realized_pnl + p.assets[s].unrealized_pnl} />
      <div className="simulation-grid">
        <PriceLine title={`${s} · 持仓股数`} {...chart} value={(p) => p.assets[s].shares} />
        <PriceLine title={`${s} · 成交量`} {...chart} value={(p) => p.assets[s].volume} />
      </div>
      <p className="muted">开 / 高 / 低 / 收：{[at.assets[s].open, at.assets[s].high, at.assets[s].low, at.assets[s].close].map(amount).join(" / ")}</p>
      {at.assets[s].forecast?.classifier_version != null && <p className="notice">
        分类器 {String(at.assets[s].forecast!.classifier_version)} · 趋势 {(Number(at.assets[s].forecast!.trend_probability)*100).toFixed(1)}%
        {" · 反转 "}{(Number(at.assets[s].forecast!.reversion_probability)*100).toFixed(1)}%
        {" · 现金/噪声 "}{(Number(at.assets[s].forecast!.cash_probability ?? at.assets[s].forecast!.noise_probability)*100).toFixed(1)}%
        。合成数据训练的策略混合权重，不是未来盈利概率。
      </p>}
      {at.assets[s].forecast?.selected_expert != null && <p className="notice">
        观察期选择的专家（按调仓日执行）：{strategyNames[String(at.assets[s].forecast!.selected_expert)] || (at.assets[s].forecast!.selected_expert === "cash" ? "现金 / 观察" : String(at.assets[s].forecast!.selected_expert))}
        {" · 已揭晓观察期："}{String(at.assets[s].forecast!.observation_start)} — {String(at.assets[s].forecast!.observation_end)}
      </p>}
      {at.assets[s].forecast?.selected_expert != null && <details><summary>{s} · 专家选择与切换记录</summary>
        <p className="muted">仅使用当时已揭晓的观察期；选择变化在后续调仓执行，不代表当日已经买入。</p>
        <table><thead><tr><th>日期</th><th>选择策略</th><th>观察起点</th><th>观察终点</th></tr></thead><tbody>
          {points.filter((p,i) => p.assets[s].forecast?.selected_expert != null && (i === 0 || p.assets[s].forecast?.selected_expert !== points[i-1].assets[s].forecast?.selected_expert)).map((p) => <tr key={stamp(p)}>
            <td>{stamp(p)}</td><td>{strategyNames[String(p.assets[s].forecast!.selected_expert)] || "现金 / 观察"}</td>
            <td>{String(p.assets[s].forecast!.observation_start)}</td><td>{String(p.assets[s].forecast!.observation_end)}</td>
          </tr>)}
        </tbody></table>
      </details>}
      <details><summary>{s} · 模型预测曲线（非实际收益）</summary>
      {[{ key: "probability", title: "上涨概率" }, { key: "mean_bps", title: "多日预测收益 bps" }, { key: "expected_return_bps", title: "分钟预测收益 bps" }].map(({ key, title }) => {
        const forecasts = points.filter((p) => typeof p.assets[s].forecast?.[key] === "number");
        return forecasts.length ? <PriceLine key={key} title={`${s} · ${title}（仅已有预测时点）`}
          points={forecasts} value={(p) => Number(p.assets[s].forecast![key])} onTrade={setChosen}
          seek={(i) => seek(points.findIndex((p) => stamp(p) === stamp(forecasts[i])))} /> : null;
      })}
      </details>
      {at.assets[s].forecast && <details><summary>{s} · 当前模型输出</summary><pre>{JSON.stringify(at.assets[s].forecast, null, 2)}</pre></details>}
    </div>)}
    <h3>逐日收益</h3>
    <svg viewBox="0 0 900 180" role="img" aria-label="组合逐日收益">
      {daily.map((d, i) => { const h = Math.abs(d.pct) / dailyMax * 70; return <rect key={d.date} x={50 + i / daily.length * 800} y={d.pct >= 0 ? 85 - h : 85} width={Math.max(.5, 800 / daily.length - 1)} height={Math.max(.5, h)} fill={pnlColor(d.pct) || "#8f9ca8"}><title>{d.date} {amount(d.pct)}%</title></rect>; })}
      <line x1="50" x2="850" y1="85" y2="85" stroke="#9ba8b4" />
      <text x="50" y="175">{daily[0]?.date}</text><text x="850" y="175" textAnchor="end">{daily[daily.length - 1]?.date}</text>
    </svg>
    <h3>成交明细 · 最近300笔</h3>
    <div className="table-wrap"><table><thead><tr><th>时间</th><th>股票</th><th>方向</th><th>股数</th><th>成交价</th><th>费用</th><th>已实现盈亏</th><th>剩余股数</th><th>原因</th></tr></thead><tbody>
      {visibleTrades.slice(-300).reverse().map((t, i) => <tr key={i}><td>{label(stamp(t))}</td><td>{t.symbol}</td><td><span aria-label={t.side} style={{ color: t.side === "buy" ? buyColor : sellColor }}>●</span></td><td>{t.quantity}</td><td>{amount(t.price)}</td><td>{amount(t.fee)}</td><td>{t.realized_pnl == null ? "—" : <Pnl value={t.realized_pnl} />}</td><td>{t.position_after}</td><td>{t.reason}</td></tr>)}
    </tbody></table></div>
    {!visibleTrades.length && <p className="notice">截至当前回放时刻没有成交，价格走势不代表已持仓。</p>}
    {shown === curve.length && <div className="replay-buttons"><DownloadButton href={tradesExport}>全部成交 CSV</DownloadButton><DownloadButton href={curveExport}>资金与各股持仓 CSV</DownloadButton>{decisionsExport && <DownloadButton href={decisionsExport}>资金分配决策 CSV</DownloadButton>}</div>}
  </div>;
}
