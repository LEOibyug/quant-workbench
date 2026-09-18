import { useEffect, useState } from "react";
import { PositionPanel, type PositionDeployment } from "./PositionPanel";
import type { Dataset } from "./types";
import { SimulationPanel } from "./SimulationPanel";
import { api } from "./api";
import { strategyNames } from "./types";
interface Deployment {
  horizon_type?: "short" | "long";
  position_config?: PositionDeployment["position_config"];
  id: string;
  name: string;
  version: string;
  published_at: string;
  symbols: string[];
  strategies: Record<string, string>;
  synthetic: boolean;
  model: {
    enabled: boolean;
    k?: number;
    probability_threshold?: number;
    horizon?: number;
    architecture?: string;
    cost_aware?: boolean;
    decision_mode?: string;
    cost_multiplier?: number;
    min_edge_bps?: number;
  };
  model_version?: string;
  model_valid_from?: string | null;
  strategy_config: Record<string, string | number>;
}
export function Workspace() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [items, setItems] = useState<Deployment[]>([]);
  const [id, setId] = useState(
    new URLSearchParams(location.search).get("deployment") || "",
  );
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const refresh = () => {
      api<Dataset[]>("/datasets").then((data) => { if (active) setDatasets(data); })
        .catch((e) => { if (active) setError(e.message); });
      return api<Deployment[]>("/deployments")
        .then((data) => {
          if (active) {
            setItems(data);
            setId((prev) =>
              data.some((d) => d.id === prev) ? prev : data[0]?.id || "",
            );
            setError("");
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  const selected = items.find((d) => d.id === id);
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">STRATEGY & MODEL LIBRARY</div>
          <h1>策略与模型展示</h1>
          <p>选择已发布的短期或长期策略，进行日内模拟或隔夜组合模拟。</p>
        </div>
        <span className="badge">已发布版本</span>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <section className="card">
        <label>
          策略与模型
          <select value={id} onChange={(e) => setId(e.target.value)}>
            <option value="">选择已发布版本</option>
            {items.map((d) => (
              <option key={d.id} value={d.id}>
                {d.horizon_type === "long" ? "长期" : "短期"} · {d.name} · {d.version}
              </option>
            ))}
          </select>
        </label>
        {!items.length && <p className="muted">暂无已发布的策略或模型。</p>}
        {selected && (
          <>
            <p>
              {selected.name} · 版本 {selected.version}
            </p>
            <small>
              发布时间：{new Date(selected.published_at).toLocaleString()}
            </small>
            {selected.synthetic && (
              <p className="notice">
                合成数据演示版本，尚未证明真实市场有效性。
              </p>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>股票</th>
                    <th>交易策略</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.symbols.map((s) => (
                    <tr key={s}>
                      <td>{s}</td>
                      <td>
                        {strategyNames[selected.strategies[s]] ||
                          selected.strategies[s]}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      {selected?.horizon_type === "long" && selected.position_config && <>
        <PositionPanel key={selected.id} datasets={datasets.filter((d) => selected.symbols.every((s) => d.symbols.includes(s)))}
          deployment={{ id: selected.id, name: selected.name, symbols: selected.symbols, position_config: selected.position_config }} />
        <section className="card"><h2>已发布长期策略参数</h2>
          <p>{selected.model.enabled ? "统计模型参与决策" : "规则策略 · 无预测模型"} · 持仓数日至数周 · 分批执行</p>
          <details><summary>查看冻结参数与交易成本</summary>
          <pre>{JSON.stringify({ ...selected.position_config, costs: Object.fromEntries(
            Object.entries(selected.position_config.costs).filter(([key]) => [
              "initial_cash", "spread_bps", "slippage_bps", "commission_per_share",
              "minimum_commission", "sell_fee_bps", "participation",
            ].includes(key)),
          ) }, null, 2)}</pre></details>
          <p className="muted">发布的是固定估计方法与风险参数；模拟仅用当时可用历史重新拟合。实时运行和实盘下单尚未启用。</p>
        </section>
      </>}
      {selected && selected.horizon_type !== "long" && (
        <>
          <SimulationPanel
            key={selected.id}
            scope="workspace"
            sourceId={selected.id}
            symbols={selected.symbols}
            cash={Number(selected.strategy_config.initial_cash)}
            validFrom={selected.model_valid_from}
          />
          <section className="card">
            <h2>时序模型</h2>
            {selected.model.enabled ? (
              <>
                <p>
                  {selected.model_version} · 窗口 {selected.model.k} · 未来{" "}
                  {selected.model.horizon || 1} 分钟预测 ·{" "}
                  {selected.model.decision_mode === "risk_scaled"
                    ? "模型调节规则风险预算"
                    : selected.model.decision_mode === "adaptive"
                      ? "自适应分位门槛 + 仓位调节"
                      : `严格概率门槛 ${selected.model.probability_threshold}`}
                </p>
                <p className="muted">
                  模型与规则共同决定入场；前 2k
                  个周期收集与适应，之后持续使用已揭晓标签更新。
                </p>
                {selected.model.decision_mode === "adaptive" && (
                  <p>
                    门槛取该股最近预测概率的滚动80%分位（下限0.5），通过后按置信度与边际缩放仓位，明显看空时否决；持续录取模型相对最自信的读数，避免长期空仓。
                  </p>
                )}
                {selected.model.decision_mode === "risk_scaled" && (
                  <p>
                    规则控制成本空间与风险，模型决定预算内的25%—100%仓位，明显看空时否决。弱预测不再全部阻止交易；这不代表预测期望收益已覆盖成本。
                  </p>
                )}
                {selected.model.cost_aware &&
                  selected.model.decision_mode !== "risk_scaled" && (
                    <p>
                      收益过滤：预测未来 {selected.model.horizon || 1}{" "}
                      分钟收益需覆盖往返成本的 {selected.model.cost_multiplier}{" "}
                      倍，另加 {selected.model.min_edge_bps} bps。
                    </p>
                  )}
              </>
            ) : (
              <p>此版本使用纯规则策略。</p>
            )}
          </section>
          <section className="card">
            <h2>策略运行参数</h2>
            <pre>{JSON.stringify(selected.strategy_config, null, 2)}</pre>
          </section>
          <p className="muted">实时运行和实盘下单尚未启用。</p>
        </>
      )}
    </>
  );
}
