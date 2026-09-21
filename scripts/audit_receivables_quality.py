"""Same-filing annual receivables/sales ratio audit, never a trading verdict."""

import argparse
from datetime import date
import json
from pathlib import Path

from build_quality_snapshots import ROOT as SEC
from quality_value_features import EXCLUDED

TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
AR = "AccountsReceivableNetCurrent"


def judge(facts, symbol, cutoff, verified=False):
    out = dict(symbol=symbol, asof=cutoff, status="证据不足", validated=False, computable=False)
    if not verified or symbol in EXCLUDED:
        return dict(**out, reason="身份未核验或不在会计可比范围")
    gaap = facts.get("facts", {}).get("us-gaap", {})

    def rows(tag):
        return [
            dict(**r, tag=tag)
            for r in gaap.get(tag, {}).get("units", {}).get("USD", [])
            if r.get("form") in ("10-K", "10-K/A")
            and r.get("filed", "9999") < cutoff
            and r.get("end", "9999") < cutoff
            and r.get("accn")
        ]

    revenue = [
        r
        for t in TAGS
        for r in rows(t)
        if "start" in r
        and 330 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 380
    ]
    if not revenue:
        return dict(**out, reason="缺少已公开年度收入")
    latest = max(revenue, key=lambda r: (r["end"], r["filed"], r["accn"]))
    end = latest["end"]
    accn = latest["accn"]
    if (date.fromisoformat(cutoff) - date.fromisoformat(end)).days > 550:
        return dict(**out, reason="最新可用年度陈旧")
    ar = [r for r in rows(AR) if r["accn"] == accn and "start" not in r]

    def unique(rs):
        values = {r["val"] for r in rs}
        return rs[0] if len(values) == 1 else None

    current_ar = unique([r for r in ar if r["end"] == end])
    if current_ar is None:
        return dict(**out, reason="最新年报缺少或冲突的净流动应收", accession=accn)
    for tag in TAGS:
        current = unique(
            [r for r in revenue if r["tag"] == tag and r["accn"] == accn and r["end"] == end]
        )
        if current is None:
            continue
        priors = sorted(
            [
                r
                for r in revenue
                if r["tag"] == tag
                and r["accn"] == accn
                and 330 <= (date.fromisoformat(end) - date.fromisoformat(r["end"])).days <= 400
            ],
            key=lambda r: r["end"],
            reverse=True,
        )
        if not priors:
            continue
        prior = unique([r for r in priors if r["end"] == priors[0]["end"]])
        if prior is None:
            continue
        prior_ar = unique([r for r in ar if r["end"] == prior["end"]])
        if prior_ar is None:
            continue
        if min(current["val"], prior["val"], prior_ar["val"]) <= 0 or current_ar["val"] < 0:
            return dict(**out, reason="收入/基期应收非正或当期应收负")
        dsri = (current_ar["val"] / current["val"]) / (prior_ar["val"] / prior["val"])
        out.update(
            computable=True,
            dsri=dsri,
            fiscal_end=end,
            accession=accn,
            sources=dict(
                revenue=current,
                prior_revenue=prior,
                receivables=current_ar,
                prior_receivables=prior_ar,
            ),
            reason="同年报可计算的应收/收入代理，不是操纵判定或盈利概率",
        )
        return out
    return dict(**out, reason="同年报同收入标签缺少可比前一年应收/收入", accession=accn)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol")
    parser.add_argument("--date", default="2025-09-01")
    args = parser.parse_args()
    identities = json.loads(
        Path("docs/research-results/2026-09-21-sec-50-issuers.json").read_text()
    )
    symbols = [args.symbol.upper()] if args.symbol else sorted(identities)
    dates = (
        [date.fromisoformat(args.date).isoformat()]
        if args.symbol
        else ["2022-09-01", "2023-09-01", "2024-09-01", "2025-09-01"]
    )
    output = []
    for s in symbols:
        p = SEC / f"{s}-facts.json"
        for day in dates:
            output.append(
                judge(
                    json.loads(p.read_text()) if p.exists() else {},
                    s,
                    day,
                    identities.get(s, {}).get("identity_verified", False),
                )
            )
    if args.symbol:
        print(json.dumps(output[0], ensure_ascii=False, indent=2))
        return
    dest = Path("docs/research-results/2026-09-21-receivables-audit.json")
    dest.write_text(
        json.dumps(dict(status="completed", results=output), ensure_ascii=False, indent=2) + "\n"
    )
    for day in dates:
        rs = [r for r in output if r["asof"] == day]
        eligible = [r for r in rs if r["computable"]]
        print(day, len(eligible), "/", len(rs), [r["symbol"] for r in eligible])


if __name__ == "__main__":
    main()
