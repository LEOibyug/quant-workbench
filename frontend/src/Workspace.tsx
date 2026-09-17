import { useEffect, useState } from "react";
import { api } from "./api";
import { strategyNames } from "./types";
interface Deployment {
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
  };
  model_version?: string;
  strategy_config: Record<string, string | number>;
}
export function Workspace() {
  const [items, setItems] = useState<Deployment[]>([]);
  const [id, setId] = useState(
    new URLSearchParams(location.search).get("deployment") || "",
  );
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const refresh = () =>
      api<Deployment[]>("/deployments")
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
          <p>查看已发布的策略与模型版本。</p>
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
                {d.name} · {d.version}
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
      {selected && (
        <>
          <section className="card">
            <h2>时序模型</h2>
            {selected.model.enabled ? (
              <>
                <p>
                  {selected.model_version} · 窗口 {selected.model.k} ·
                  下一周期上涨概率门槛 {selected.model.probability_threshold}
                </p>
                <p className="muted">
                  模型与规则共同决定入场；前 2k
                  个周期收集与适应，之后持续使用已揭晓标签更新。
                </p>
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
