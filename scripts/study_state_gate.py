"""Research-only causal applicability gates; never deployed or reported as validated."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from build_quality_snapshots import snapshot
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository

ROOT = Path("docs/research-results")
SEC = Path("artifacts/research/sec-quality")


def judge(history, asof, facts=None, submission=None, require_quality=True):
    rows = history[history.day <= asof].sort_values("day")
    checks = []

    def check(name, value, condition, threshold):
        checks.append(dict(name=name, value=value, passed=bool(condition), threshold=threshold))

    missing = []
    if len(rows) < 127:
        missing.append("至少127日历史")
    else:
        p = rows.close.to_numpy()
        avg = float(p[-126:].mean())
        mom = float(np.log(p[-1] / p[-64]))
        liquidity = float((rows.close * rows.volume).tail(20).median())
        check("半年趋势", float(p[-1]), p[-1] > avg, dict(operator=">", value=avg))
        check("季度动量", mom, mom > 0, dict(operator=">", value=0))
        check("中位日成交额USD", liquidity, liquidity >= 1e7, dict(operator=">=", value=1e7))
    financial = None
    if require_quality:
        if facts is None:
            missing.append("财报未获取")
        else:
            financial = snapshot(facts, submission or {}, asof)
            annual = financial["annual"]
            if len(annual) < 3:
                missing.append("三个可比年度财务数据")
            else:
                ends = [date.fromisoformat(r["end"]) for r in annual]
                gaps = [(ends[i] - ends[i + 1]).days for i in range(2)]
                age = (date.fromisoformat(asof) - ends[0]).days
                if age > 550 or not all(330 <= g <= 400 for g in gaps):
                    missing.append("年度陈旧或间隔不可比")
                check(
                    "三年净利润和经营现金流为正",
                    [[r["net_income"], r["operating_cash_flow"]] for r in annual],
                    financial["positive_income_and_cashflow_three_years"],
                    "每年均>0",
                )
                cash = sum(r["operating_cash_flow"] for r in annual)
                earnings = sum(r["net_income"] for r in annual)
                check(
                    "三年现金支持", cash - earnings, cash >= earnings, "经营现金流合计>=净利润合计"
                )
                check(
                    "最新年度收入变化",
                    annual[0]["revenue"] - annual[1]["revenue"],
                    annual[0]["revenue"] >= annual[1]["revenue"],
                    ">=0",
                )
    candidate = (
        "证据不足" if missing else ("通过" if all(c["passed"] for c in checks) else "未通过")
    )
    return dict(
        version="state-quality-gate-v0",
        asof=asof,
        status="证据不足",
        validation="仅固定候选条件，尚未完成独立验证",
        candidate_status=candidate,
        missing=missing,
        checks=checks,
        financial=financial,
        reevaluate="下一交易日收盘或新财报公开后重新判断",
    )


def main():
    original = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        x["config"]
        for x in original["results"]
        if x["method"] == "fixed_ensemble" and x["cost_multiplier"] == 1
    )
    pools = {
        "original20": Repository().load_dataset(original["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    dest = ROOT / "2026-09-21-state-gate.json"
    for pool, frame in pools.items():
        base = rule_forecasts(frame, PositionConfig(**cfg))
        for quality in (False, True):
            decisions = {}
            counts = {"通过": 0, "未通过": 0, "证据不足": 0}
            start_judgments = {}
            for symbol, g in frame.groupby("symbol"):
                path = SEC / f"{symbol}-facts.json"
                facts = json.loads(path.read_text()) if path.exists() else None
                subpath = SEC / f"{symbol}-submission.json"
                sub = json.loads(subpath.read_text()) if subpath.exists() else None
                for day in sorted(g.day):
                    if day < "2025-09-01":
                        continue
                    j = judge(g, day, facts, sub, quality)
                    decisions[(day, symbol)] = j["candidate_status"] == "通过"
                    counts[j["candidate_status"]] += 1
                    if symbol not in start_judgments:
                        start_judgments[symbol] = j
            gated = {
                k: {**v, "target_weight": v["target_weight"] if decisions.get(k, False) else 0}
                for k, v in base.items()
            }
            for multiplier in (1, 2):
                costs = dict(cfg["costs"])
                for k in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[k] *= multiplier
                config = PositionConfig(**{**cfg, "costs": costs})
                # Only this local research invocation supplies a frozen candidate forecast map.
                with patch("quant_workbench.position.daily_forecasts", return_value=gated):
                    run = simulate_positions(
                        frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                    )
                row = dict(
                    pool=pool,
                    candidate="quality_state" if quality else "state_only",
                    cost_multiplier=multiplier,
                    config=run["config"],
                    metrics=run["metrics"],
                    coverage=counts,
                    start_judgments=start_judgments,
                    contributions=run["contributions"],
                )
                results.append(row)
                dest.write_text(
                    json.dumps(
                        dict(status="running", results=results), ensure_ascii=False, indent=2
                    )
                )
                print(
                    pool,
                    row["candidate"],
                    multiplier,
                    round(run["metrics"]["return_pct"], 3),
                    round(run["metrics"]["max_drawdown_pct"], 3),
                    counts,
                    flush=True,
                )
    dest.write_text(
        json.dumps(dict(status="completed", results=results), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
