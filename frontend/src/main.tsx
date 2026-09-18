import { lazy, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
const Research = lazy(() =>
  import("./Research").then((m) => ({ default: m.Research })),
);
import { Workspace } from "./Workspace";
import "./style.css";
function App() {
  const [research, setResearch] = useState(location.pathname !== "/workspace");
  const [visitedResearch, setVisitedResearch] = useState(research);
  const [visitedWorkspace, setVisitedWorkspace] = useState(!research);
  useEffect(() => {
    const update = () => {
      const next = location.pathname !== "/workspace";
      setResearch(next);
      if (next) setVisitedResearch(true);
      else setVisitedWorkspace(true);
    };
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  function navigate(event: React.MouseEvent<HTMLAnchorElement>, path: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    history.pushState(null, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          Q<span> / </span>WORKBENCH
        </div>
        <div className="local">
          {research ? "美股策略开发" : "策略与模型展示"}
        </div>
        <nav aria-label="工作区导航">
          <a href="/research" onClick={(e) => navigate(e, "/research")}
            aria-current={research ? "page" : undefined}>策略开发</a>
          <a href="/workspace" onClick={(e) => navigate(e, "/workspace")}
            aria-current={!research ? "page" : undefined}>策略与模型展示</a>
        </nav>
        <div className="aside-footer">
          历史研究 v0.3
          <br />
          规则策略 × 时序模型
          <br />
          统一工作台 · 无实盘下单
        </div>
      </aside>
      <main>
        <header>
          <span>QUANT WORKBENCH / US EQUITIES</span>
          <span>策略开发与展示</span>
        </header>
        <Suspense fallback={<p>加载面板…</p>}>
          <div hidden={!research}>{visitedResearch && <Research />}</div>
          <div hidden={research}>{visitedWorkspace && <Workspace />}</div>
        </Suspense>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
