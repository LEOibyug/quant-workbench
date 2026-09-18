import { useEffect, useState } from "react";
import { api, computeUrl } from "./api";

export function ComputeConnection() {
  const initial = new URL(computeUrl);
  const [host, setHost] = useState(initial.hostname);
  const [port, setPort] = useState(initial.port || (initial.protocol === "https:" ? "443" : "80"));
  const [protocol, setProtocol] = useState(initial.protocol);
  const [status, setStatus] = useState("正在连接计算服务…");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const health = await api<{ service: string; protocol_version: number }>("/health", {
          signal: AbortSignal.timeout(8000),
        });
        if (health.service !== "quant-workbench-compute" || health.protocol_version !== 1)
          throw new Error("服务版本不兼容");
        if (active) setStatus(`已连接 · ${computeUrl}`);
      } catch {
        if (active) setStatus(`计算服务未连接 · ${computeUrl}`);
      }
    }
    void refresh();
    const timer = setInterval(refresh, 15000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const hostname = host.trim();
      if (!hostname || /[\s/?#@]/.test(hostname)) throw new Error("请输入主机名或 IP 地址，不含路径");
      if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535)
        throw new Error("端口范围为 1–65535");
      const address = hostname.includes(":") && !hostname.startsWith("[") ? `[${hostname}]` : hostname;
      const candidate = new URL(`${protocol}//${address}:${port}`).origin;
      const response = await fetch("/api/health", {
        headers: { "X-Quant-Compute-URL": candidate }, signal: AbortSignal.timeout(8000),
      });
      const health = await response.json();
      if (!response.ok) throw new Error(health.detail || "连接失败");
      if (health.service !== "quant-workbench-compute" || health.protocol_version !== 1)
        throw new Error("该地址不是兼容的计算服务，请确认端口");
      localStorage.setItem("quant.compute.url", candidate);
      // Reload atomically: in-flight observers keep their original server until unload.
      location.reload();
    } catch (e) {
      setError(`连接未保存：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card compute-connection" aria-label="计算服务连接">
      <strong role="status">{status}</strong>
      <form onSubmit={connect} className="connection-fields">
        <label>协议<select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
          <option value="http:">HTTP</option><option value="https:">HTTPS</option>
        </select></label>
        <label>计算服务器<input required value={host} onChange={(e) => setHost(e.target.value)} placeholder="192.168.1.20" /></label>
        <label>端口<input required type="number" min="1" max="65535" value={port} onChange={(e) => setPort(e.target.value)} /></label>
        <button disabled={busy} type="submit">{busy ? "连接中…" : "连接并保存"}</button>
      </form>
      <small>计算在服务器持续运行；切换连接会重新加载页面。进度、结果和导出均来自所选服务器。</small>
      {error && <p className="notice error" role="alert">{error}</p>}
    </section>
  );
}
