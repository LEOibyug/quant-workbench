import { DownloadButton } from "./ProgressNotice";
import type { Result } from "./types";
const number = (n: number | null | undefined, d = 2) =>
  n == null
    ? "—"
    : n.toLocaleString(undefined, {
        maximumFractionDigits: d,
        minimumFractionDigits: d,
      });
export function Results({ result: r, id }: { result: Result; id: string }) {
  const values = r.curve.flatMap((p) => [p.equity, p.benchmark]),
    low = Math.min(...values),
    high = Math.max(...values),
    range = high - low || 1;
  const maxDD = Math.max(...r.curve.map((p) => p.drawdown_pct), 0.001);
  const drawdowns = r.curve
    .map(
      (p, i) =>
        `${50 + (i / (r.curve.length - 1 || 1)) * 870},${30 + (p.drawdown_pct / maxDD) * 80}`,
    )
    .join(" ");
  const points = (key: "equity" | "benchmark") =>
    r.curve
      .map(
        (p, i) =>
          `${50 + (i / (r.curve.length - 1 || 1)) * 870},${220 - ((p[key] - low) / range) * 180}`,
      )
      .join(" ");
  return (
    <>
      {r.synthetic && (
        <div className="notice">
          合成行情演示：下列收益用于验证软件流程，不构成真实股票的投资表现。
        </div>
      )}
      {r.prior_test_exposure && (
        <div className="notice">
          这些股票的重叠日期曾作为最终测试暴露，请将本次结果视作探索性研究。
        </div>
      )}
      <div className="metric-grid">
        {[
          ["净收益率", "return_pct", "%"],
          ["最大回撤", "max_drawdown_pct", "%"],
          ["日收益 Sharpe", "daily_sharpe", ""],
          ["成交次数", "trade_count", ""],
          ["佣金及规费", "fees", " USD"],
          ["价差及滑点", "impact_cost", " USD"],
        ].map(([label, key, unit]) => (
          <div className="metric" key={key}>
            <span>{label}</span>
            <strong>
              {number(r.metrics[key])}
              {unit}
            </strong>
          </div>
        ))}
      </div>
      <section className="card">
        <div className="section-heading">
          <h2>资金曲线</h2>
          <span className="muted">
            ● 策略　<span className="benchmark">● 无成本日内持有</span>
          </span>
        </div>
        <svg
          className="equity-chart"
          viewBox="0 0 950 265"
          role="img"
          aria-label="策略与日内持有基准资金曲线"
        >
          <text x="0" y="32">
            {number(high, 0)}
          </text>
          <text x="0" y="224">
            {number(low, 0)}
          </text>
          <line x1="50" y1="220" x2="920" y2="220" stroke="#ccd4dc" />
          <polyline
            points={points("benchmark")}
            fill="none"
            stroke="#a7b6c5"
            strokeWidth="2"
          />
          <polyline
            points={points("equity")}
            fill="none"
            stroke="#157c72"
            strokeWidth="2.5"
          />
          <text x="50" y="250">
            {r.start}
          </text>
          <text x="840" y="250">
            {r.end}
          </text>
        </svg>
        <p className="muted">
          {r.curve_downsampled
            ? "显示抽样曲线，CSV 保留全部分钟记录。"
            : "显示全部分钟记录。"}{" "}
          基准每日开盘买入、收盘卖出，日间复利、不扣费、不隔夜。
        </p>
      </section>
      <section className="card">
        <h2>策略回撤</h2>
        <svg
          className="equity-chart"
          viewBox="0 0 950 140"
          role="img"
          aria-label="资金曲线相对历史高点的回撤"
        >
          <text x="0" y="30">
            0%
          </text>
          <text x="0" y="110">
            {number(maxDD)}%
          </text>
          <line x1="50" y1="30" x2="920" y2="30" stroke="#ccd4dc" />
          <polyline
            points={drawdowns}
            fill="none"
            stroke="#bd7656"
            strokeWidth="2"
          />
        </svg>
      </section>
      <section className="card">
        <h2>逐股收益贡献</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>策略</th>
                <th>净损益 USD</th>
              </tr>
            </thead>
            <tbody>
              {r.contributions.map((c) => (
                <tr key={c.symbol}>
                  <td>{c.symbol}</td>
                  <td>{c.strategy}</td>
                  <td>{number(c.net_profit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {r.rule_baseline && (
        <section className="card">
          <h2>联合决策与纯规则对照</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>运行方式</th>
                  <th>净收益率</th>
                  <th>最大回撤</th>
                  <th>成交次数</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["策略 + 时序模型", r.metrics],
                  ["纯规则", r.rule_baseline],
                ].map(([label, m]) => {
                  const metrics = m as Record<string, number | null>;
                  return (
                    <tr key={String(label)}>
                      <td>{String(label)}</td>
                      <td>{number(metrics.return_pct)}%</td>
                      <td>{number(metrics.max_drawdown_pct)}%</td>
                      <td>{number(metrics.trade_count, 0)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {r.model_statistics && (
            <details>
              <summary>在线学习统计</summary>
              <pre>{JSON.stringify(r.model_statistics, null, 2)}</pre>
            </details>
          )}
        </section>
      )}
      <section className="card">
        <div className="section-heading">
          <h2>成交记录</h2>
          <div className="exports">
            {["trades", "curve", "daily_returns"].map((kind, i) => (
              <DownloadButton
                key={kind}
                href={`/api/experiments/${id}/export/${r.phase}/${kind}`}
              >
                {["成交", "曲线", "日收益"][i]} CSV ↗
              </DownloadButton>
            ))}
          </div>
        </div>
        <p className="muted">
          共 {r.total_trades} 笔，页面最多显示 300 笔。时间为 UTC。
        </p>
        <div className="table-wrap trades">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>股票</th>
                <th>方向</th>
                <th>数量</th>
                <th>价格</th>
                <th>费用</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              {r.trades.map((t, i) => (
                <tr key={i}>
                  <td>{t.timestamp.replace("T", " ").slice(0, 19)}</td>
                  <td>{t.symbol}</td>
                  <td>{t.side === "buy" ? "买入" : "卖出"}</td>
                  <td>{t.quantity}</td>
                  <td>{number(t.price)}</td>
                  <td>{number(t.fee)}</td>
                  <td>{t.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!r.trades.length && (
          <p>本阶段未产生交易；检查规则条件、概率门槛和数据范围。</p>
        )}
      </section>
      {r.decision_funnel && (
        <section className="card">
          <h2>逐股入场机会诊断</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>规则候选分钟</th>
                  <th>模型拦截分钟</th>
                  <th>实际买入次数</th>
                  <th>资金/流动性/成本未成交</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(r.decision_funnel).map(([symbol, raw]) => {
                  const f = raw as Record<string, number>;
                  return (
                    <tr key={symbol}>
                      <td>{symbol}</td>
                      <td>{f.rule_candidates}</td>
                      <td>{f.model_blocked_candidates}</td>
                      <td>{f.entry_fills}</td>
                      <td>{f.unfilled_entry_attempts}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <small>候选按分钟计数，不等于独立订单数。</small>
        </section>
      )}
      <section className="card">
        <h2>模拟约定</h2>
        <ul>
          {r.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </section>
    </>
  );
}
