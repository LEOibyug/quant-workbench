"""Gross profitability and asset investment with filing provenance."""

import argparse
import json
from datetime import date
from pathlib import Path

from audit_financial_derivations import enrich
from build_quality_snapshots import annual_values
from quality_value_features import EXCLUDED


def judge(facts, day, symbol, verified=True):
    base = dict(symbol=symbol, asof=day, status="证据不足", method="gross_investment_v0")
    if symbol in EXCLUDED or not verified:
        return dict(**base, reason="会计范围或发行人身份不满足")
    enriched, _ = enrich(facts, day)
    gp = {r["end"]: r for r in annual_values(enriched, "gross_profit", day)}
    assets = {r["end"]: r for r in annual_values(facts, "assets", day)}
    common = sorted(set(gp) & set(assets), reverse=True)
    if not common:
        return dict(**base, reason="无同年度毛利润/资产")
    end = common[0]
    prior = next(
        (
            e
            for e in sorted(assets, reverse=True)
            if 330 <= (date.fromisoformat(end) - date.fromisoformat(e)).days <= 400
        ),
        None,
    )
    if prior is None or (date.fromisoformat(day) - date.fromisoformat(end)).days > 550:
        return dict(**base, reason="年度不可比或陈旧")
    if min(assets[end]["val"], assets[prior]["val"]) <= 0:
        return dict(**base, reason="资产非正")
    return dict(
        **base,
        candidate_eligible=True,
        gross=float(gp[end]["val"] / assets[end]["val"]),
        growth=float(assets[end]["val"] / assets[prior]["val"] - 1),
        fiscal_end=end,
        sources=dict(gross_profit=gp[end], assets=assets[end], prior_assets=assets[prior]),
        reason="财务代理可计算，策略适用性未验证",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    symbol = args.symbol.upper()
    day = date.fromisoformat(args.date).isoformat()
    path = next(
        (
            p
            for p in Path("artifacts/research/sec-quality").glob("*-facts.json")
            if p.name.removesuffix("-facts.json") == symbol
        ),
        None,
    )
    identities = json.loads(
        Path("docs/research-results/2026-09-21-sec-50-issuers.json").read_text()
    )
    result = (
        judge(
            json.loads(path.read_text()),
            day,
            symbol,
            identities.get(symbol, {}).get("identity_verified", False),
        )
        if path
        else dict(symbol=symbol, asof=day, status="证据不足", reason="缺少财报缓存")
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
