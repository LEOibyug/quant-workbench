"""Causal annual quality and lagged earnings yield, explicitly unvalidated."""

from datetime import date

import numpy as np
from build_quality_snapshots import annual_values

EXCLUDED = set("BRK.B JPM MA SOFI V BAC GS MS PLD NEE SO".split())


def judge(facts, day, symbol, price, verified=True):
    base = dict(symbol=symbol, asof=day, status="证据不足")
    if symbol in EXCLUDED:
        return dict(**base, reason="不在预先定义的会计可比范围")
    if not verified:
        return dict(**base, reason="发行人身份待核验")
    series = {
        k: annual_values(facts, k, day) for k in ["net_income", "operating_cash_flow", "assets"]
    }
    common = sorted(
        set.intersection(*(set(x["end"] for x in rs) for rs in series.values())), reverse=True
    )[:3]
    if len(common) < 3:
        return dict(**base, reason="缺少三个可比年度")
    ends = [date.fromisoformat(x) for x in common]
    if (date.fromisoformat(day) - ends[0]).days > 550 or not all(
        330 <= (ends[i] - ends[i + 1]).days <= 400 for i in range(2)
    ):
        return dict(**base, reason="年度陈旧或不可比")
    rows = {
        k: [next(x for x in values if x["end"] == end) for end in common]
        for k, values in series.items()
    }
    if any(x["val"] <= 0 for rs in rows.values() for x in rs):
        return dict(**base, reason="未满足三年利润/现金流/资产均正")
    roa = np.array(
        [n["val"] / a["val"] for n, a in zip(rows["net_income"], rows["assets"], strict=True)]
    )
    cash = np.array(
        [
            n["val"] / a["val"]
            for n, a in zip(rows["operating_cash_flow"], rows["assets"], strict=True)
        ]
    )
    quality = float(np.median(roa) + np.median(cash) - np.std(roa, ddof=1))
    latest = rows["net_income"][0]
    shares = []
    units = (
        facts["facts"]
        .get("us-gaap", {})
        .get("WeightedAverageNumberOfDilutedSharesOutstanding", {})
        .get("units", {})
    )
    for x in units.get("shares", []):
        if (
            x.get("filed", "9999") < day
            and x.get("form") in ["10-K", "10-K/A"]
            and x.get("end") == latest["end"]
            and x.get("start") == latest.get("start")
            and x["val"] > 0
        ):
            shares.append(x)
    share = max(shares, key=lambda x: (x["filed"], x.get("accn", ""))) if shares else None
    return dict(
        **base,
        reason="候选财务条件通过，策略适用性未验证",
        candidate_pass=True,
        quality=quality,
        roa=roa.tolist(),
        cashflow_assets=cash.tolist(),
        earnings_yield=float(latest["val"] / share["val"] / price) if share else None,
        share_source=share,
        annual_sources=rows,
    )
