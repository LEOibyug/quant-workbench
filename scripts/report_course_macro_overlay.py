"""Report macro-overlay results against frozen fixed controls."""
import gzip
import json
import math
from pathlib import Path
import numpy as np

ROOT = Path("docs/research-results")


def main():
    report = json.loads((ROOT / "2026-09-22-course-macro-overlay.json").read_text())
    assert report["status"] == "completed"
    rows = report["results"]
    controls = json.loads(gzip.decompress((ROOT / "2026-09-22-trend-pullback.full.json.gz").read_bytes()))["results"]
    banded = json.loads(gzip.decompress((ROOT / "2026-09-22-banded-execution.full.json.gz").read_bytes()))["results"]
    base = {(r["pool"], r["cost_multiplier"], r["policy"]): r for r in controls if r["method"] == "fixed_ensemble" and r["policy"] == "legacy"}
    base.update({(r["pool"], r["cost_multiplier"], "banded"): r for r in banded})
    lines = ["# 课件宏观状态叠加实验", "", "本实验将课件中的宏观状态判断落地为股票池内部的因果代理：股票池等权几何价格指数相对200日均线的趋势状态，与高于各自200日几何均线的股票广度，连续映射为 0.25–1.00 的总仓位系数。选股、三专家信号、风险缩放、费用和日期均冻结；没有按结果调参。", "", "## 数学定义", "", "对收盘价 p_{i,t}，股票池指数 I_t=exp(mean_i(log p_{i,t}))。趋势 T_t=1[I_t>SMA_200(I)_t]，广度 B_t=mean_i 1[p_{i,t}>GMA_200(p_i)_t]，宏观系数 s_t=0.25+0.75(T_t+B_t)/2。前200个观测日系数固定为1。macro_overlay 的目标权重是固定三专家目标权重的平均值乘以 s_t，再经过既有组合风险缩放与执行层。", "", "## 结果", "", "|股票池|费用倍数|执行|收益%|相对 fixed 同执行百分点|回撤%|交易数|平均仓位%|", "|---|---:|---|---:|---:|---:|---:|"]
    deltas = {}
    for r in rows:
        m = r["metrics"]
        control = base[(r["pool"], r["cost_multiplier"], r["policy"])]
        delta = m["return_pct"] - control["metrics"]["return_pct"]
        deltas.setdefault((r["pool"], r["cost_multiplier"], r["policy"]), delta)
        lines.append(f"|{r['pool']}|{r['cost_multiplier']}|{r['policy']}|{m['return_pct']:.3f}|{delta:+.3f}|{m['max_drawdown_pct']:.3f}|{m['trade_count']}|{m['average_gross_exposure_pct']:.2f}|")
    non_original = [r for r in rows if r["pool"] != "original20"]
    gates = []
    for policy in ("legacy", "banded"):
        for cost in (1, 2):
            ds = [deltas[(r["pool"], cost, policy)] for r in non_original if r["policy"] == policy and r["cost_multiplier"] == cost]
            # one row per pool after the filter above
            passed = sum(x > 0 for x in ds) >= math.ceil(5 * 0.8) and float(np.median(ds)) > 0
            gates.append((policy, cost, sum(x > 0 for x in ds), float(np.median(ds)), passed))
    lines += ["", "## 预先登记的跨池门槛", "", "非 original20 的5个池中，正常和双倍费用、legacy与banded分别要求至少4/5收益改善且收益差中位数为正；回撤不作为收益筛选条件，但会单独报告。", "", "|执行|费用倍数|改善池数|收益差中位数百分点|通过|", "|---|---:|---:|---:|---|"]
    for policy, cost, wins, median, passed in gates:
        lines.append(f"|{policy}|{cost}|{wins}/5|{median:+.3f}|{passed}|")
    accepted = all(x[-1] for x in gates)
    lines += ["", f"## 结论", "", f"跨池门槛：{'通过' if accepted else '未通过'}。{'该 overlay 可作为研究候选继续观察，但不改变默认策略。' if not accepted else '该候选满足本轮预先登记门槛，仍需独立时期确认后才能考虑升级。'}", "", "局限：宏观代理只使用当前股票池价格，没有债券、黄金、现金利息或完整总回报；200日状态需要预热；结果是历史回测，不构成实盘收益保证。", "", "复现：`uv run --locked python scripts/study_course_macro_overlay.py`。"]
    (ROOT / "2026-09-22-course-macro-overlay.md").write_text("\n".join(lines) + "\n")
    (ROOT / "2026-09-22-course-macro-overlay-gates.json").write_text(json.dumps(dict(gates=[dict(policy=p, cost_multiplier=c, wins=w, median_difference_pp=m, passed=v) for p,c,w,m,v in gates], accepted=accepted), indent=2) + "\n")
    print("accepted:", accepted)


if __name__ == "__main__":
    main()
