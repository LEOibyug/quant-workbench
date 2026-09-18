import { useEffect, useState } from "react";
import { api, post, computeFetch, computeUrl } from "./api";
export interface ProgressState {
  stage: string;
  status: string;
  done?: number;
  total?: number | null;
  unit?: string;
  started_at?: string;
  finished_at?: string;
  error?: string | null;
}
export function ProgressNotice({
  value,
}: {
  value: ProgressState | null | undefined;
}) {
  const [now, setNow] = useState(Date.now());
  const active = value?.status === "running" || value?.status === "queued";
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active, value?.started_at]);
  if (!value) return null;
  const elapsed =
    value.started_at && (active || value.finished_at)
      ? Math.max(
          0,
          Math.floor(
            ((value.finished_at ? Date.parse(value.finished_at) : now) -
              Date.parse(value.started_at)) /
              1000,
          ),
        )
      : null;
  const pct =
    value.total && value.total > 0
      ? Math.min(100, Math.round(((value.done || 0) / value.total) * 100))
      : null;
  return (
    <div
      className={`operation-progress ${value.status === "failed" ? "error" : ""}`}
      role="status"
      aria-live="polite"
      aria-busy={active}
    >
      <div>
        <strong>
          {active && <span className="activity-spinner" aria-hidden="true" />}
          {value.stage}
        </strong>
        <span>{elapsed !== null && `耗时 ${elapsed} 秒`}</span>
      </div>
      {active && (
        <progress
          aria-label={`${value.stage}进度`}
          max={100}
          value={pct === null ? undefined : pct}
        />
      )}
      <small>
        {pct !== null ? `当前阶段 ${pct}% · ` : active ? "正在处理 · " : ""}
        {value.done !== undefined && (value.unit || value.total)
          ? `${value.done.toLocaleString()}${value.total ? ` / ${value.total.toLocaleString()}` : ""} ${value.unit || ""}`
          : ""}
        {value.error}
      </small>
    </div>
  );
}
interface Operation<T> extends ProgressState {
  id: string;
  result: T | null;
}
const operationKey = `quant.pending.research.operation:${computeUrl}`;
export function pendingOperation(): {
  id: string;
  kind: "download" | "train";
} | null {
  try {
    return JSON.parse(localStorage.getItem(operationKey) || "null");
  } catch {
    return null;
  }
}
export async function observeOperation<T>(
  id: string,
  update: (state: ProgressState) => void,
): Promise<T> {
  let failures = 0;
  while (true) {
    let job: Operation<T>;
    try {
      job = await api<Operation<T>>(`/research/operations/${id}`);
      failures = 0;
    } catch (e) {
      if (++failures >= 5)
        throw new Error(
          `进度连接中断；后台任务 ${id} 可能仍在运行。点击重新连接任务可恢复。${(e as Error).message}`,
        );
      update({ status: "running", stage: "进度连接中断，正在重连" });
      await new Promise((resolve) => setTimeout(resolve, 1500));
      continue;
    }
    update(job);
    if (job.status !== "queued" && job.status !== "running") {
      if (pendingOperation()?.id === id) localStorage.removeItem(operationKey);
      if (job.status !== "completed" || !job.result)
        throw new Error(job.error || "任务未完成");
      return job.result;
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}
export async function runOperation<T>(
  kind: "download" | "train",
  body: unknown,
  update: (state: ProgressState) => void,
): Promise<T> {
  if (pendingOperation())
    throw new Error("还有未确认完成的任务，请先重新连接任务");
  const job = await post<Operation<T>>(`/research/operations/${kind}`, body);
  localStorage.setItem(operationKey, JSON.stringify({ id: job.id, kind }));
  update(job);
  return observeOperation<T>(job.id, update);
}
export function DownloadButton({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  const [state, setState] = useState<ProgressState | null>(null);
  const pending = state?.status === "running";
  async function download() {
    const started_at = new Date().toISOString();
    setState({ status: "running", stage: "正在生成导出文件", started_at });
    try {
      const response = await computeFetch(href);
      if (!response.ok) {
        let detail = "导出失败";
        try {
          detail = (await response.json()).detail || detail;
        } catch {
          /* Non-JSON server response. */
        }
        throw new Error(detail);
      }
      const total = !response.headers.get("content-encoding")
        ? Number(response.headers.get("content-length")) || null
        : null;
      const parts: Uint8Array<ArrayBuffer>[] = [];
      let done = 0;
      const reader = response.body?.getReader();
      if (!reader) throw new Error("浏览器不支持下载流");
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        parts.push(new Uint8Array(chunk.value));
        done += chunk.value.length;
        setState({
          status: "running",
          stage: "正在下载文件",
          started_at,
          done,
          total,
          unit: "字节",
        });
      }
      const url = URL.createObjectURL(
        new Blob(parts, { type: "text/csv;charset=utf-8" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download =
        response.headers
          .get("content-disposition")
          ?.match(/filename="([^"]+)"/)?.[1] || "export.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setState({
        status: "completed",
        stage: "文件已交给浏览器保存",
        done,
        unit: "字节",
        started_at,
        finished_at: new Date().toISOString(),
      });
    } catch (e) {
      setState({
        status: "failed",
        stage: "下载失败",
        error: (e as Error).message,
        started_at,
        finished_at: new Date().toISOString(),
      });
    }
  }
  return (
    <div className="download-control">
      <button type="button" disabled={pending} onClick={download}>
        {pending ? "下载中…" : children}
      </button>
      <ProgressNotice value={state} />
    </div>
  );
}
