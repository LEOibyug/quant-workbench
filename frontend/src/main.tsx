import { lazy, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
const Research = lazy(() =>
  import("./Research").then((m) => ({ default: m.Research })),
);
import { Workspace } from "./Workspace";
import { api } from "./api";
import "./style.css";
function App() {
  const research = location.pathname !== "/workspace";
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    api("/health")
      .then(() => setConnected(true))
      .catch(() => setConnected(false));
  }, []);
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          Q<span> / </span>WORKBENCH
        </div>
        <div className="local">
          {research ? "本地美股研究" : "策略与模型展示"}
        </div>
        <nav aria-label="工作区导航">
          {research && (
            <a href="/research" aria-current="page">
              01　策略研究
            </a>
          )}
          <a
            href="/workspace"
            target={research ? "_blank" : undefined}
            rel="noopener noreferrer"
            aria-current={!research ? "page" : undefined}
          >
            策略与模型展示
          </a>
        </nav>
        <div className="aside-footer">
          历史研究 v0.2
          <br />
          规则策略 × 时序模型
          <br />
          本地计算 · 无实盘下单
        </div>
      </aside>
      <main>
        <header>
          <span>LOCAL / US EQUITIES</span>
          <span role="status">
            {connected ? "● 本地 API 已连接" : "○ 正在连接本地 API"}
          </span>
        </header>
        <Suspense fallback={<p>加载研究面板…</p>}>
          {research ? <Research /> : <Workspace />}
        </Suspense>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
