"""SEC annual fundamentals selected by filing availability, not fiscal date alone."""

import json
import time
from pathlib import Path

import httpx

ROOT = Path("artifacts/research/sec-quality")
CIKS = {
    "AAPL": 320193,
    "MSFT": 789019,
    "NVDA": 1045810,
    "AMZN": 1018724,
    "META": 1326801,
    "GOOGL": 1652044,
    "AMD": 2488,
    "TSLA": 1318605,
    "COST": 909832,
    "JNJ": 200406,
    "ACN": 1467373,
    "GILD": 882095,
    "INTU": 896878,
    "LMT": 936468,
    "LOW": 60667,
    "MCD": 63908,
    "NEE": 753308,
    "NKE": 320187,
    "PLD": 1045609,
    "SO": 92122,
    "ADBE": 796343,
    "CRM": 1108524,
    "CSCO": 858877,
    "IBM": 51143,
    "INTC": 50863,
    "QCOM": 804328,
    "TXN": 97476,
    "MRK": 310158,
    "PG": 80424,
    "CAT": 18230,
}
TAGS = {
    "gross_profit": ["GrossProfit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "assets": ["Assets"],
}


def annual_values(facts, metric, cutoff):
    from datetime import date

    candidates = []
    for priority, tag in enumerate(TAGS[metric]):
        for row in (
            facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
        ):
            if row.get("form") not in ["10-K", "10-K/A"] or row.get("filed", "9999") >= cutoff:
                continue
            if row.get("end", "9999") >= cutoff:
                continue
            if metric != "assets":
                if "start" not in row:
                    continue
                duration = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
                if not 330 <= duration <= 380:
                    continue
            candidates.append({**row, "tag": tag, "priority": priority})
    # Each fiscal end is represented once. Prefer primary tag, then newest already-public filing.
    by_end = {}
    for row in sorted(
        candidates, key=lambda r: (r["end"], -r["priority"], r["filed"], r.get("accn", ""))
    ):
        by_end[row["end"]] = row
    return [by_end[e] for e in sorted(by_end, reverse=True)]


def snapshot(facts, submission, cutoff):
    series = {k: annual_values(facts, k, cutoff) for k in TAGS}
    required = ["net_income", "operating_cash_flow", "revenue", "assets"]
    ends = set.intersection(*(set(r["end"] for r in series[k]) for k in required))
    ends = sorted(ends, reverse=True)[:3]
    rows = []
    for end in ends:
        item = {"end": end, "sources": {}}
        for k in TAGS:
            r = next((r for r in series[k] if r["end"] == end), None)
            item[k] = None if r is None else r["val"]
            if r:
                item["sources"][k] = {
                    q: r.get(q) for q in ["tag", "start", "end", "filed", "accn", "form"]
                }
        rows.append(item)
    sic = str(submission.get("sic", ""))
    # SIC is current metadata: descriptive only, never a historical eligibility filter here.
    return dict(
        cutoff=cutoff,
        entity=facts.get("entityName"),
        cik=facts.get("cik"),
        current_sic=sic,
        current_sic_description=submission.get("sicDescription"),
        current_sic_is_point_in_time=False,
        annual=rows,
        complete_three_years=len(rows) == 3,
        positive_income_and_cashflow_three_years=len(rows) == 3
        and all(r["net_income"] > 0 and r["operating_cash_flow"] > 0 for r in rows),
        gross_profit_assets_latest=(
            rows[0]["gross_profit"] / rows[0]["assets"]
            if rows and rows[0]["gross_profit"] is not None and rows[0]["assets"] > 0
            else None
        ),
    )


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    results = {}
    with httpx.Client(
        timeout=40,
        headers={
            "User-Agent": "QuantWorkbench financial research (local research client)",
            "Accept-Encoding": "gzip, deflate",
        },
    ) as client:
        for symbol, cik in CIKS.items():
            data = {}
            for kind, url in [
                ("facts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"),
                ("submission", f"https://data.sec.gov/submissions/CIK{cik:010d}.json"),
            ]:
                path = ROOT / f"{symbol}-{kind}.json"
                if not path.exists():
                    response = client.get(url)
                    if response.status_code != 200:
                        raise ValueError(f"{symbol} {kind} HTTP {response.status_code}")
                    path.write_text(response.text)
                    time.sleep(0.25)
                data[kind] = json.loads(path.read_text())
            if symbol not in data["submission"].get("tickers", []):
                raise ValueError(f"{symbol}: CIK ticker mismatch")
            results[symbol] = snapshot(data["facts"], data["submission"], "2025-09-01")
            print(
                symbol,
                results[symbol]["entity"],
                results[symbol]["complete_three_years"],
                results[symbol]["positive_income_and_cashflow_three_years"],
                flush=True,
            )
            Path("docs/research-results/2026-09-21-quality-data-audit.json").write_text(
                json.dumps(dict(status="running", snapshots=results), indent=2)
            )
    Path("docs/research-results/2026-09-21-quality-data-audit.json").write_text(
        json.dumps(dict(status="completed", snapshots=results), indent=2)
    )


if __name__ == "__main__":
    main()
