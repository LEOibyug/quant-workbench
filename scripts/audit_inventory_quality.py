"""Same-filing annual inventory/cost ratio audit, never a trading verdict."""

import argparse
import json
from datetime import date
from pathlib import Path

from build_quality_snapshots import ROOT as SEC
from quality_value_features import EXCLUDED

TAGS = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
INVENTORY_TAG = "InventoryNet"


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

    cost = [
        r
        for t in TAGS
        for r in rows(t)
        if "start" in r
        and 330 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 380
    ]
    if not cost:
        return dict(**out, reason="缺少已公开年度销售成本")
    latest = max(cost, key=lambda r: (r["end"], r["filed"], r["accn"]))
    end = latest["end"]
    accn = latest["accn"]
    if (date.fromisoformat(cutoff) - date.fromisoformat(end)).days > 550:
        return dict(**out, reason="最新可用年度陈旧")
    ar = [r for r in rows(INVENTORY_TAG) if r["accn"] == accn and "start" not in r]

    def unique(rs):
        values = {r["val"] for r in rs}
        return rs[0] if len(values) == 1 else None

    current_inventory = unique([r for r in ar if r["end"] == end])
    if current_inventory is None:
        return dict(**out, reason="最新年报缺少或冲突的净存货", accession=accn)
    for tag in TAGS:
        current = unique(
            [r for r in cost if r["tag"] == tag and r["accn"] == accn and r["end"] == end]
        )
        if current is None:
            continue
        priors = sorted(
            [
                r
                for r in cost
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
        prior_inventory = unique([r for r in ar if r["end"] == prior["end"]])
        if prior_inventory is None:
            continue
        if (
            min(current["val"], prior["val"], prior_inventory["val"]) <= 0
            or current_inventory["val"] < 0
        ):
            return dict(**out, reason="销售成本/基期存货非正或当期存货负")
        inventory_cost_ratio = (current_inventory["val"] / current["val"]) / (
            prior_inventory["val"] / prior["val"]
        )
        out.update(
            computable=True,
            inventory_cost_ratio=inventory_cost_ratio,
            fiscal_end=end,
            accession=accn,
            sources=dict(
                cost=current,
                prior_cost=prior,
                inventory=current_inventory,
                prior_inventory=prior_inventory,
            ),
            reason="同年报可计算的存货/销售成本代理，不是操纵判定或盈利概率",
        )
        return out
    return dict(**out, reason="同年报同销售成本标签缺少可比前一年存货/销售成本", accession=accn)


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
    dest = Path("docs/research-results/2026-09-21-inventory-audit.json")
    dest.write_text(
        json.dumps(dict(status="completed", results=output), ensure_ascii=False, indent=2) + "\n"
    )
    for day in dates:
        rs = [r for r in output if r["asof"] == day]
        eligible = [r for r in rs if r["computable"]]
        print(day, len(eligible), "/", len(rs), [r["symbol"] for r in eligible])


if __name__ == "__main__":
    main()
