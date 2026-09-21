"""Cash-flow accrual candidate using only publicly filed annual observations."""

from datetime import date

from build_quality_snapshots import annual_values
from quality_value_features import EXCLUDED


def judge(facts, day, symbol, verified=True):
    base = dict(symbol=symbol, asof=day, status="证据不足", method="cash_accrual_v0")
    if symbol in EXCLUDED or not verified:
        return dict(**base, reason="会计范围不适用或身份未核验")
    series = {
        k: {r["end"]: r for r in annual_values(facts, k, day)}
        for k in ("net_income", "operating_cash_flow", "assets")
    }
    common = sorted(
        set(series["net_income"]) & set(series["operating_cash_flow"]) & set(series["assets"]),
        reverse=True,
    )
    if not common:
        return dict(**base, reason="缺少同财年利润/现金流/资产")
    end = common[0]
    prior = next(
        (
            e
            for e in sorted(series["assets"], reverse=True)
            if 330 <= (date.fromisoformat(end) - date.fromisoformat(e)).days <= 400
        ),
        None,
    )
    if prior is None or (date.fromisoformat(day) - date.fromisoformat(end)).days > 550:
        return dict(**base, reason="年度资产不可比或陈旧")
    sources = {k: series[k][end] for k in series}
    sources["prior_assets"] = series["assets"][prior]
    if sources["net_income"].get("start") != sources["operating_cash_flow"].get("start"):
        return dict(**base, reason="利润与现金流年度起点不一致", sources=sources)
    ni, cf, a, a0 = [
        sources[k]["val"] for k in ("net_income", "operating_cash_flow", "assets", "prior_assets")
    ]
    if min(a, a0) <= 0 or ni <= 0:
        return dict(**base, reason="资产或最近净利润非正", sources=sources)
    return dict(
        **base,
        candidate_eligible=True,
        score=float((ni - cf) / ((a + a0) / 2)),
        sources=sources,
        reason="可计算现金流应计代理；收益判别未验证",
    )
