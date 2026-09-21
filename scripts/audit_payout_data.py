"""Audit same-filing cash payout components without inferring missing zeros."""

import argparse
import json
from datetime import date
from pathlib import Path

TAGS = {
    "repurchases": "PaymentsForRepurchaseOfCommonStock",
    "dividends": "PaymentsOfDividendsCommonStock",
    "issuance": "ProceedsFromIssuanceOfCommonStock",
}


def annual(facts, tag, cutoff):
    rows = facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
    out = {}
    for r in rows:
        if r.get("form") not in ("10-K", "10-K/A") or r.get("filed", "9999") >= cutoff:
            continue
        if not r.get("start") or not r.get("accn") or r.get("end", "9999") >= cutoff:
            continue
        if not 330 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 380:
            continue
        key = (r["accn"], r["start"], r["end"])
        out.setdefault(key, []).append({**r, "tag": tag})
    return out


def judge(facts, symbol, cutoff):
    cutoff = date.fromisoformat(cutoff).isoformat()
    result = dict(
        symbol=symbol,
        asof=cutoff,
        status="证据不足",
        method="cash-payout-audit-v0",
        candidate_eligible=False,
        reasons=[],
        sources={},
    )
    groups = {name: annual(facts, tag, cutoff) for name, tag in TAGS.items()}
    result["available_annual_components"] = {k: len(v) for k, v in groups.items()}
    common = set.intersection(*(set(rows) for rows in groups.values()))
    if not common:
        result["reasons"].append("缺少同一申报、相同年度起止的普通股回购/分红/发行现金记录；不补零")
        return result
    key = max(common, key=lambda k: (k[2], max(r["filed"] for r in groups["repurchases"][k]), k[0]))
    if (date.fromisoformat(cutoff) - date.fromisoformat(key[2])).days > 550:
        result["reasons"].append("最近共同财务年度陈旧，超过550日")
        return result
    for component, rows in groups.items():
        values = rows[key]
        if len({r["val"] for r in values}) != 1 or values[0]["val"] < 0:
            result["reasons"].append(f"{component}同申报记录冲突或负值，需人工核验")
            return result
        result["sources"][component] = max(values, key=lambda r: r["filed"])
    values = {k: v["val"] for k, v in result["sources"].items()}
    result.update(
        fiscal_end=key[2],
        cash_components_complete=True,
        cash_net_payout_usd=values["repurchases"] + values["dividends"] - values["issuance"],
    )
    # Do not sum potentially overlapping option proceeds or equate cash issuance with dilution.
    options = annual(facts, "ProceedsFromStockOptionsExercised", cutoff).get(key, [])
    result["same_filing_option_proceeds"] = options
    result["reasons"] += [
        "现金发行不覆盖非现金股权薪酬、换股并购与可转债转股，不能据此判断净稀释",
        "期权行权现金与普通股发行标签可能重叠，尚未查阅报表附注，不相加",
        "尚无判断时点的完整历史总市值分母，不输出净派息收益率",
        "财务字段可计算不等于策略适用性已验证",
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol")
    parser.add_argument("--date", default="2025-09-01")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path("artifacts/research/sec-quality")
    paths = (
        [root / f"{args.symbol.upper()}-facts.json"]
        if args.symbol
        else sorted(root.glob("*-facts.json"))
    )
    dates = [args.date] if args.symbol else ["2022-09-01", "2023-09-01", "2024-09-01", "2025-09-01"]
    results = []
    for path in paths:
        facts = json.loads(path.read_text()) if path.exists() else {}
        for day in dates:
            results.append(judge(facts, path.name.removesuffix("-facts.json"), day))
    payload = dict(results=results)
    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
