"""Summarize all frozen deployment starts; never choose a best start for deployment."""

import gzip
import json
from pathlib import Path

import numpy as np

ROOT = Path("docs/research-results")


def main():
    path = ROOT / "2026-09-22-start-sensitivity.json"
    data = json.loads(path.read_text())
    full = json.loads(gzip.decompress(path.with_suffix(".full.json.gz").read_bytes()))
    checks = json.loads((ROOT / "2026-09-22-start-sensitivity-checks.json").read_text())
    assert (
        data["status"] == full["status"] == "completed"
        and len(data["results"]) == len(full["results"]) == 40
    )
    rows = data["results"]
    assert {(r["start"], r["cost_multiplier"]) for r in rows} == {
        (s, m) for s in checks["starts"] for m in [1, 2]
    }
    lines = [
        "# 同一策略不同启动日期：40账户部署敏感性",
        "",
        "本实验只改变启动日期，规则、股票池、终点和参数不变。全部结果保留，不选择最佳起点；它不提供新的股票适用性判据。",
        "",
        "## 冻结设计与比较范围",
        "",
        "协议5ec7f84先于结果。22股低资产增长三分组，自2022-09-01起前20个交易日各开一个100000现金账户，终点均2025-09-01；正常/双倍费用共40账户。保持逆波动、20日调仓、分批成交、单股止损和永久组合停机，不因失败关闭风险。",
        "",
        "当前引擎每20个交易日从账户起点安排决策，所以起点变动同时改变调仓相位、建仓及资金/风险路径。区间长度相差最多19交易日，数据高度重叠，不能作为40次独立试验或纯调仓相位的因果识别。原价分红/公司行动缺口沿用，不声称完整净总回报。",
        "",
        "## 全体统计",
        "",
        "|费用|收益最小%|中位数%|最大%|亏损账户/20|停机账户/20|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    summaries = {}
    for mult in [1, 2]:
        part = [r for r in rows if r["cost_multiplier"] == mult]
        returns = [r["metrics"]["return_pct"] for r in part]
        summary = dict(
            minimum=min(returns),
            median=float(np.median(returns)),
            maximum=max(returns),
            negative=sum(x < 0 for x in returns),
            halted=sum(r["metrics"]["halted"] for r in part),
        )
        summaries[mult] = summary
        lines.append(
            f"|{mult}|{summary['minimum']:+.3f}|{summary['median']:+.3f}|{summary['maximum']:+.3f}|{summary['negative']}|{summary['halted']}|"
        )
    lines += [
        "",
        "正常费用20个起点有10个亏损，全部20个最终永久停机；双倍费用同样10个亏损且全部停机。"
        "中位数接近零，不能以某个最佳起点约+2.58%替代完整分布，策略稳定性仍未成立。",
        "",
        "## 每个启动日期",
        "",
        "|启动日|正常收益%|正常回撤%|正常首次停机|双倍收益%|双倍首次停机|",
        "|---|---:|---:|---|---:|---|",
    ]
    for start in checks["starts"]:
        a = next(r for r in rows if r["start"] == start and r["cost_multiplier"] == 1)
        b = next(r for r in rows if r["start"] == start and r["cost_multiplier"] == 2)
        lines.append(
            f"|{start}|{a['metrics']['return_pct']:+.3f}|"
            f"{a['metrics']['max_drawdown_pct']:.3f}|{a['first_halt'] or '未停机'}|"
            f"{b['metrics']['return_pct']:+.3f}|{b['first_halt'] or '未停机'}|"
        )
    lines += [
        "",
        "## 解释和验证",
        "",
        "正常费用9月1日启动−1.1717%、首次停机2023-10-27；仅改为9月2日启动+0.4153%、停机2024-07-01。这个例子说明单一启动日的盈亏不能直接解释为企业类型适用或不适用，也不意味着应等待某个事后优选日期。",
        "",
        "首个启动日期的两费用账户全部既有指标及逐股贡献精确复现；每次映射决策日与引擎相对20日调仓日历一致。40账户的完整压缩档案及起点×费用组合核验齐全。源行情哈希及原财报来源清单保留，未下载新数据、未改生产策略。",
        "",
        "复现：`uv run --locked python scripts/study_asset_start_sensitivity.py`，随后 "
        "`uv run --locked python scripts/report_asset_start_sensitivity.py`。"
            "JSON包含全部费用、换手、贡献、权益曲线与停机；完整档案含逐日持仓。",
        "",
        "下一步如检验分散调仓日期，必须作为预先固定的新资金分配机制，使用同一总资金和所有相位，不能事后仅保留盈利相位。本轮没有把任何事后组合当作已实现收益。仍需更完整数据与独立确认，总体目标未完成。",
    ]
    (ROOT / "2026-09-22-start-sensitivity.md").write_text("\n".join(lines) + "\n")
    (ROOT / "2026-09-22-start-sensitivity-summary.json").write_text(
        json.dumps(summaries, indent=2) + "\n"
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
