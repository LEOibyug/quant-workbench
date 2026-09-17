import { useEffect, useState } from "react";
import { api, post } from "./api";
import { SimulationPanel } from "./SimulationPanel";
import { ProgressNotice, type ProgressState } from "./ProgressNotice";
import { Results } from "./Results";
import { phaseNames } from "./types";
import type { Experiment, Phase, Result } from "./types";
export function ExperimentRunner({ selectedId }: { selectedId?: string }) {
  const [experiments, setExperiments] = useState<Experiment[]>([]),
    [id, setId] = useState(selectedId || "");
  const [phase, setPhase] = useState<Phase>("validation"),
    [result, setResult] = useState<Result | null>(null),
    [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [action, setAction] = useState<"run" | "publish">("run");
  const [actionProgress, setActionProgress] = useState<ProgressState | null>(
    null,
  );
  const [published, setPublished] = useState<{
    id: string;
    experimentId: string;
  } | null>(null);
  useEffect(() => {
    if (selectedId) setId(selectedId);
  }, [selectedId]);
  useEffect(() => {
    setPublished(null);
    setActionProgress(null);
  }, [id]);
  async function publish() {
    setAction("publish");
    setActionProgress({
      status: "running",
      stage: "发布独立策略与模型快照",
      started_at: new Date().toISOString(),
    });
    setPending(true);
    setError("");
    try {
      const result = await post<{ id: string }>(`/experiments/${id}/publish`);
      setPublished({ id: result.id, experimentId: id });
      setActionProgress((p) => ({
        ...p,
        status: "completed",
        stage: "发布完成",
        finished_at: new Date().toISOString(),
      }));
    } catch (e) {
      setError((e as Error).message);
      setActionProgress((p) => ({
        ...p,
        status: "failed",
        stage: "操作失败",
        error: (e as Error).message,
        finished_at: new Date().toISOString(),
      }));
    } finally {
      setPending(false);
    }
  }
  useEffect(() => {
    let active = true;
    const refresh = () =>
      api<Experiment[]>("/experiments")
        .then((items) => {
          if (active) {
            setExperiments(items);
            setId((prev) => prev || items[0]?.id || "");
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    refresh();
    const timer = setInterval(refresh, 2500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  const experiment = experiments.find((e) => e.id === id),
    run = experiment?.runs.find((r) => r.phase === phase);
  useEffect(() => {
    let active = true;
    setResult(null);
    if (id && run?.status === "completed")
      api<Result>(`/experiments/${id}/results/${phase}`)
        .then((r) => {
          if (active) setResult(r);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [id, phase, run?.status]);
  const running = experiments.some((e) =>
    e.runs.some((r) => r.status === "running"),
  );
  const testLocked =
    phase === "test" &&
    !experiment?.runs.some(
      (r) => r.phase === "validation" && r.status === "completed",
    );
  async function launch() {
    setAction("run");
    setActionProgress({
      status: "running",
      stage: "提交回测任务",
      started_at: new Date().toISOString(),
    });
    setPending(true);
    setError("");
    try {
      await post(`/experiments/${id}/run/${phase}`);
      setExperiments(await api<Experiment[]>("/experiments"));
      setActionProgress(null);
    } catch (e) {
      setError((e as Error).message);
      setActionProgress((p) => ({
        ...p,
        status: "failed",
        stage: "操作失败",
        error: (e as Error).message,
        finished_at: new Date().toISOString(),
      }));
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">RESEARCH EVALUATION</div>
          <h2>实验验证与测试</h2>
          <p>运行冻结的实验，检查扣费表现与在线适应过程。</p>
        </div>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <section className="card">
        <label>
          冻结实验
          <select value={id} onChange={(e) => setId(e.target.value)}>
            <option value="">选择实验</option>
            {experiments.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name} · {e.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        {experiment && (
          <>
            <div className="tabs">
              {(Object.keys(phaseNames) as Phase[]).map((p) => (
                <button
                  key={p}
                  className={p === phase ? "active" : ""}
                  onClick={() => setPhase(p)}
                >
                  {phaseNames[p]}
                  <small>
                    {experiment.runs.find((r) => r.phase === p)?.status ||
                      "未运行"}
                  </small>
                </button>
              ))}
            </div>
            <p>
              {experiment.symbols.join(" / ")} · {experiment.start} —{" "}
              {experiment.end} ·{" "}
              {experiment.model.enabled ? "策略 + 在线时序模型" : "纯规则策略"}
            </p>
            {testLocked && (
              <p className="notice">
                先完成验证阶段，再查看最终测试。若根据最终测试结果改进策略，需要新的未见数据进行评估。
              </p>
            )}
            <details>
              <summary>查看冻结的策略、交易成本与模型参数</summary>
              <pre>
                {JSON.stringify(
                  {
                    策略与成本: experiment.config,
                    时序模型: experiment.model,
                    离线训练: experiment.model_metadata,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
            <button
              className="primary"
              disabled={
                pending || running || testLocked || run?.status === "completed"
              }
              onClick={launch}
            >
              {run?.status === "completed"
                ? "已完成 · 结果已固定"
                : run?.status === "running"
                  ? "计算中…"
                  : pending && action === "run"
                    ? "正在提交…"
                    : `运行${phaseNames[phase]}`}
            </button>
            {run && (
              <ProgressNotice
                value={{
                  ...run.progress,
                  status: run.status,
                  error: run.error,
                  stage:
                    run.status === "completed"
                      ? `${phaseNames[phase]}运行完成`
                      : run.status === "failed"
                        ? "运行失败"
                        : run.progress?.stage || "计算中，等待进度",
                }}
              />
            )}
            {action === "run" && <ProgressNotice value={actionProgress} />}
            <div className="publication">
              <button
                disabled={
                  pending ||
                  !experiment.runs.some(
                    (r) => r.phase === "validation" && r.status === "completed",
                  )
                }
                onClick={publish}
              >
                {pending && action === "publish"
                  ? "正在发布…"
                  : "发布策略与模型到展示页"}
              </button>
              {action === "publish" && (
                <ProgressNotice value={actionProgress} />
              )}
              {published?.experimentId === id && (
                <a
                  className="button primary"
                  href={`/workspace?deployment=${published.id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  打开展示页 ↗
                </a>
              )}
              <p className="muted">
                仅发布独立的策略与模型版本。行情、训练过程及实验结果保留在研究页。
              </p>
            </div>
            {run?.error && <p className="notice error">{run.error}</p>}
          </>
        )}
        {!experiments.length && (
          <p className="muted">还没有实验。请先获取行情并创建实验。</p>
        )}
      </section>
      {experiment && (
        <SimulationPanel
          key={experiment.id}
          scope="research"
          sourceId={experiment.id}
          symbols={experiment.symbols}
          cash={experiment.config.initial_cash}
          validated={experiment.runs.some(
            (r) => r.phase === "validation" && r.status === "completed",
          )}
          bounds={{
            train: [experiment.start, experiment.train_end],
            validation: [experiment.train_end, experiment.validation_end],
            test: [experiment.validation_end, experiment.end],
          }}
        />
      )}
      {result && <Results result={result} id={id} />}
    </>
  );
}
