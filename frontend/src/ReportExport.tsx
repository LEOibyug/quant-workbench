import { useState } from "react";

export function ReportExport() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function exportReport(print = false) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      window.dispatchEvent(new Event("quant:pause-replay"));
      await document.fonts.ready;
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      if (print) { window.print(); return; }
      const node = document.getElementById("workbench-report");
      if (!node) throw new Error("未找到展示页面，请刷新后重试");
      const { toBlob } = await import("html-to-image");
      const width = Math.ceil(node.getBoundingClientRect().width);
      const height = Math.ceil(node.scrollHeight);
      // Bound both dimensions and total canvas area without cropping the long report.
      const pixelRatio = Math.min(2, 30000 / Math.max(width, height), Math.sqrt(60_000_000 / (width * height)));
      const blob = await toBlob(node, {
        width, height, pixelRatio,
        backgroundColor: getComputedStyle(document.documentElement).backgroundColor,
        filter: (element) => !(element instanceof HTMLElement && (element.hidden || element.hasAttribute("data-report-exclude"))),
        style: { margin: "0", maxWidth: "none", overflow: "visible" },
      });
      if (!blob) throw new Error("长图生成失败，请尝试打印 / 保存 PDF");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `quant-report-${new Date().toISOString().replace(/[:.]/g, "-")}.png`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setError(`导出失败：${(e as Error).message}`);
    } finally { setBusy(false); }
  }
  return <div data-report-exclude className="report-export">
    <button disabled={busy} onClick={() => void exportReport()}>{busy ? "准备报告…" : "导出完整长图 PNG"}</button>
    <button disabled={busy} onClick={() => void exportReport(true)}>打印 / 保存 PDF</button>
    <small>按当前回放时刻和展开状态导出整页；长图保留页面布局，PDF由浏览器分页。</small>
    {error && <p className="notice error" role="alert">{error}</p>}
  </div>;
}
