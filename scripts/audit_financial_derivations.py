"""Derive gross profit only from matched filing-period revenue and cost facts."""

import copy
import json
from pathlib import Path

from audit_fscore_data import SEC, judge, observations
from build_quality_snapshots import annual_values

COST_TAGS = ("CostOfRevenue", "CostOfGoodsAndServicesSold")


def enrich(facts, cutoff):
    copied = copy.deepcopy(facts)
    gaap = copied.setdefault("facts", {}).setdefault("us-gaap", {})
    revenues = annual_values(facts, "revenue", cutoff)
    direct = {r["end"]: r for r in annual_values(facts, "gross_profit", cutoff)}
    audit = []
    for revenue in revenues:
        if not revenue.get("accn"):
            continue
        candidates = []
        for tag in COST_TAGS:
            for cost in (
                facts.get("facts", {})
                .get("us-gaap", {})
                .get(tag, {})
                .get("units", {})
                .get("USD", [])
            ):
                if (
                    cost.get("filed", "9999") < cutoff
                    and cost.get("form") in ("10-K", "10-K/A")
                    and all(cost.get(k) == revenue.get(k) for k in ("accn", "start", "end"))
                    and cost["val"] >= 0
                ):
                    candidates.append({**cost, "tag": tag})
        if not candidates:
            continue
        values = {r["val"] for r in candidates}
        if len(values) != 1:
            audit.append(dict(end=revenue["end"], status="conflicting_cost_tags"))
            continue
        cost = candidates[0]
        amount = revenue["val"] - cost["val"]
        explicit = direct.get(revenue["end"])
        matched = (
            explicit
            and explicit.get("accn") == revenue.get("accn")
            and explicit.get("start") == revenue.get("start")
        )
        status = (
            "derived"
            if explicit is None
            else (
                "direct_reconciles"
                if matched and abs(explicit["val"] - amount) <= max(1, abs(revenue["val"]) * 1e-6)
                else "direct_not_comparable_or_mismatch"
            )
        )
        audit.append(
            dict(
                end=revenue["end"],
                status=status,
                revenue=revenue,
                cost=cost,
                derived_value=amount,
                direct=explicit,
            )
        )
        if explicit is None:
            row = {k: v for k, v in revenue.items() if k not in ("tag", "priority")}
            row.update(
                val=amount,
                derivation="same_filing_revenue_minus_cost",
                component_sources={"revenue": revenue, "cost": cost},
            )
            gaap.setdefault("GrossProfit", {}).setdefault("units", {}).setdefault("USD", []).append(
                row
            )
    return copied, audit


def debt_diagnostic(facts, cutoff):
    series = {
        tag: observations(facts, [tag], cutoff)
        for tag in ("LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent")
    }
    common = set.intersection(*(set(s) for s in series.values()))
    results = []
    for end in sorted(common, reverse=True)[:2]:
        rows = [series[t][end] for t in series]
        if len({r.get("accn") for r in rows}) != 1:
            continue
        total, noncurrent, current = [r["val"] for r in rows]
        tolerance = max(1, abs(total) * 1e-4)
        results.append(
            dict(
                end=end,
                total_tag=total,
                noncurrent=noncurrent,
                current=current,
                equals_sum=abs(total - noncurrent - current) <= tolerance,
                equals_noncurrent=abs(total - noncurrent) <= tolerance,
                filing=rows[0].get("accn"),
            )
        )
    return results


def main():
    cutoff = "2025-09-01"
    results = []
    for path in sorted(SEC.glob("*-facts.json")):
        symbol = path.name.removesuffix("-facts.json")
        facts = json.loads(path.read_text())
        enriched, audit = enrich(facts, cutoff)
        before = judge(facts, cutoff, symbol, verified=symbol != "XOM")
        after = judge(enriched, cutoff, symbol, verified=symbol != "XOM")
        results.append(
            dict(
                symbol=symbol,
                before_unknown=before.get("unknown"),
                after=after,
                gross_profit_audit=audit,
                debt_audit=debt_diagnostic(facts, cutoff),
            )
        )
    complete = [r["symbol"] for r in results if r["after"].get("unknown") == ["no_equity_offering"]]
    report = dict(asof=cutoff, results=results, complete_eight=complete, complete_nine=[])
    Path("docs/research-results/2026-09-21-financial-derivations.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    print("Eight-signal coverage", len(complete), complete, flush=True)


if __name__ == "__main__":
    main()
