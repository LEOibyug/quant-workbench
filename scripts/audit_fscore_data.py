"""Point-in-time coverage audit; missing financial signals stay unknown."""

import argparse
import json
from datetime import date
from pathlib import Path

from build_quality_snapshots import annual_values
from quality_value_features import EXCLUDED

SEC = Path("artifacts/research/sec-quality")
SPECS = {
    "current_assets": (["AssetsCurrent"], False),
    "current_liabilities": (["LiabilitiesCurrent"], False),
    "long_debt": (["LongTermDebtNoncurrent"], False),
    "current_debt": (["LongTermDebtCurrent"], False),
    "equity": (["StockholdersEquity"], False),
    "common_shares": (["CommonStockSharesOutstanding"], False),
    "issuance_cash": (["ProceedsFromIssuanceOfCommonStock"], True),
}


def observations(facts, tags, cutoff, annual=False, unit="USD"):
    result = {}
    for tag in reversed(tags):
        records = []
        for row in (
            facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit, [])
        ):
            if (
                row.get("filed", "9999") >= cutoff
                or row.get("end", "9999") >= cutoff
                or row.get("form") not in ("10-K", "10-K/A")
            ):
                continue
            if annual and (
                "start" not in row
                or not 330
                <= (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
                <= 380
            ):
                continue
            records.append(row)
        for row in sorted(records, key=lambda r: (r["filed"], r.get("accn", ""))):
            result[row["end"]] = {**row, "tag": tag}
    return result


def judge(facts, asof, symbol, verified=True):
    base = dict(
        symbol=symbol, asof=asof, status="证据不足", method="financial-improvement-coverage-v0"
    )
    if symbol in EXCLUDED or not verified:
        return dict(**base, reason="预先排除会计不可比企业或身份未核验", signals={})
    metrics = {
        key: {r["end"]: r for r in annual_values(facts, key, asof)}
        for key in ("net_income", "operating_cash_flow", "revenue", "gross_profit", "assets")
    }
    for key, (tags, annual) in SPECS.items():
        metrics[key] = observations(
            facts, tags, asof, annual, unit="shares" if key == "common_shares" else "USD"
        )
    ends = sorted(metrics["net_income"], reverse=True)[:3]
    if (
        len(ends) < 3
        or (date.fromisoformat(asof) - date.fromisoformat(ends[0])).days > 550
        or not all(
            330 <= (date.fromisoformat(ends[j]) - date.fromisoformat(ends[j + 1])).days <= 400
            for j in (0, 1)
        )
    ):
        return dict(**base, reason="缺少三个相邻且足够新的年度", signals={})

    def val(key, year):
        row = metrics[key].get(ends[year])
        return None if row is None else float(row["val"])

    def ratio(a, b):
        return a / b if a is not None and b is not None and b > 0 else None

    def delta(a, b):
        return a > b if a is not None and b is not None else None

    roa = [ratio(val("net_income", j), val("assets", j + 1)) for j in (0, 1)]
    cash = ratio(val("operating_cash_flow", 0), val("assets", 1))
    leverage = []
    for j in (0, 1):
        values = [
            val("long_debt", j),
            val("current_debt", j),
            val("assets", j),
            val("assets", j + 1),
        ]
        leverage.append(
            ratio(values[0] + values[1], (values[2] + values[3]) / 2)
            if all(v is not None for v in values)
            else None
        )
    liquidity = [ratio(val("current_assets", j), val("current_liabilities", j)) for j in (0, 1)]
    margin = [ratio(val("gross_profit", j), val("revenue", j)) for j in (0, 1)]
    turnover = [ratio(val("revenue", j), val("assets", j + 1)) for j in (0, 1)]
    signals = dict(
        profit_positive=delta(roa[0], 0),
        cash_positive=delta(cash, 0),
        roa_improving=delta(roa[0], roa[1]),
        cash_exceeds_income=delta(cash, roa[0]),
        leverage_declining=delta(leverage[1], leverage[0]),
        liquidity_improving=delta(liquidity[0], liquidity[1]),
        margin_improving=delta(margin[0], margin[1]),
        turnover_improving=delta(turnover[0], turnover[1]),
        no_equity_offering=None,
    )
    # A cash-flow tag or unchanged share count is not an audited equity-offering history.
    return dict(
        **base,
        reason="候选信号覆盖审计；策略适用性未验证",
        fiscal_ends=ends,
        signals=signals,
        known_positive=sum(v is True for v in signals.values()),
        score_definition="八项GAAP财务代理指标加未知增发项；不是完整原文F-score",
        limitations=[
            "NetIncomeLoss未逐份核验为原文的非常项前利润",
            "尚未构建全市场账面市值比最高五分位资格",
            "未核验增发记录；未证明分数能判断策略适用性",
        ],
        unknown=[k for k, v in signals.items() if v is None],
        score_lower=sum(v is True for v in signals.values()),
        score_upper=sum(v is True or v is None for v in signals.values()),
        metrics=dict(
            roa=roa,
            cash_assets=cash,
            leverage=leverage,
            liquidity=liquidity,
            margin=margin,
            turnover=turnover,
        ),
        issuance_cash_observation=metrics["issuance_cash"].get(ends[0]),
        sources={
            k: {end: r for end, r in series.items() if end in ends} for k, series in metrics.items()
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", help="单股查询；省略则生成50股覆盖报告")
    parser.add_argument("--date", default="2025-09-01")
    args = parser.parse_args()
    asof = date.fromisoformat(args.date).isoformat()
    if args.symbol:
        symbol = args.symbol.strip().upper()
        # Match a cached filename instead of using user input as a path.
        path = next(
            (p for p in SEC.glob("*-facts.json") if p.name.removesuffix("-facts.json") == symbol),
            None,
        )
        result = (
            judge(json.loads(path.read_text()), asof, symbol, verified=symbol != "XOM")
            if path
            else dict(symbol=symbol, asof=asof, status="证据不足", reason="缺少财报缓存")
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    rows = []
    for path in sorted(SEC.glob("*-facts.json")):
        symbol = path.name.removesuffix("-facts.json")
        facts = json.loads(path.read_text())
        rows.append(judge(facts, asof, symbol, verified=symbol != "XOM"))
    report = dict(
        asof=asof,
        results=rows,
        complete_eight=[
            r["symbol"] for r in rows if len(r.get("signals", {})) == 9 and len(r["unknown"]) == 1
        ],
        complete_nine=[r["symbol"] for r in rows if r.get("signals") and not r["unknown"]],
    )
    Path("docs/research-results/2026-09-21-fscore-coverage.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    print(
        "Companies",
        len(rows),
        "complete eight",
        report["complete_eight"],
        "complete nine",
        report["complete_nine"],
        flush=True,
    )
    for r in rows:
        if r.get("signals"):
            print(
                r["symbol"], r["score_lower"], r["score_upper"], ",".join(r["unknown"]), flush=True
            )


if __name__ == "__main__":
    main()
