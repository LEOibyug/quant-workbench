import type { PortfolioPoint, PortfolioTrade } from "./PortfolioCharts";

export function DailyCandles({ symbol, points, trades, onTrade, seek }: {
  symbol: string; points: PortfolioPoint[]; trades: PortfolioTrade[];
  onTrade: (trade: PortfolioTrade) => void; seek: (index: number) => void;
}) {
  const width = Math.max(900, points.length * 9 + 100);
  const x = (i: number) => 65 + (i + .5) * (width - 100) / points.length;
  const assets = points.map((p) => p.assets[symbol]);
  const low = Math.min(...assets.map((a) => a.low), ...trades.map((t) => t.price));
  const high = Math.max(...assets.map((a) => a.high), ...trades.map((t) => t.price));
  const pad = Math.max((high - low) * .12, .01);
  const y = (v: number) => 210 - (v - low + pad) / (high - low + 2 * pad) * 160;
  const maxVolume = Math.max(1, ...assets.map((a) => a.volume));
  const indices = new Map(points.map((p, i) => [p.date, i]));
  return <section className="daily-candles">
    <h3>{symbol} · 日 K 线与买卖点 USD</h3>
    <div><svg width="100%" viewBox={`0 0 ${width} 310`}
      style={{ display: "block" }} role="img" aria-label={`${symbol} 日 K 线与成交量`}>
      <text x="5" y="50">{high.toFixed(2)}</text><text x="5" y="210">{low.toFixed(2)}</text>
      <text x="5" y="240">成交量</text>
      {assets.map((a, i) => {
        const color = a.close > a.open ? "#d04b4b" : a.close < a.open ? "#148565" : "#8f9ca8";
        return <g key={points[i].date} onClick={() => seek(i)} style={{ cursor: "pointer" }}>
          <title>{points[i].date} · 开 {a.open} 高 {a.high} 低 {a.low} 收 {a.close} · 成交量 {a.volume}</title>
          <line x1={x(i)} x2={x(i)} y1={y(a.high)} y2={y(a.low)} stroke={color} />
          <rect x={x(i)-3} y={Math.min(y(a.open), y(a.close))} width="6" height={Math.max(1,Math.abs(y(a.open)-y(a.close)))} fill={color} />
          <rect x={x(i)-3} y={280-a.volume/maxVolume*45} width="6" height={Math.max(.5,a.volume/maxVolume*45)} fill={color} />
        </g>;
      })}
      {trades.map((t,i) => {
        const index=indices.get(t.date); if(index == null) return null;
        return <path key={i} d="M -2 -17 H 2 V -8 H 6 L 0 0 L -6 -8 H -2 Z"
          transform={`translate(${x(index)},${y(t.price)})`} fill={t.side === "buy" ? "#148565" : "#d04b4b"}
          stroke="white" strokeWidth=".7" className="trade-marker" data-side={t.side}
          tabIndex={0} role="button" aria-label={`${t.side} ${symbol} ${t.date} ${t.quantity} @ ${t.price}`}
          onClick={() => onTrade(t)} onKeyDown={(e) => { if(e.key === "Enter" || e.key === " ") {e.preventDefault();onTrade(t);} }}>
          <title>{t.date} · {t.side === "buy" ? "买入" : "卖出"} {t.quantity} @ {t.price}</title>
        </path>;
      })}
      <text x="65" y="305">{points[0].date}</text><text x={width-35} y="305" textAnchor="end">{points[points.length-1].date}</text>
    </svg></div>
  </section>;
}
