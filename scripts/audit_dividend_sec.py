"""Annual cash-paid per-share reconciliation; not a trading eligibility screen."""

import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path("docs/research-results")
TAG = "CommonStockDividendsPerShareCashPaid"


def audit(symbol, facts, events):
    raw = (
        facts.get("facts", {})
        .get("us-gaap", {})
        .get(TAG, {})
        .get("units", {})
        .get("USD/shares", [])
    )
    rows = [
        r
        for r in raw
        if r.get("form") in ["10-K", "10-K/A"]
        and r.get("filed", "9999") <= "2026-09-22"
        and r.get("start")
        and "2022-01-01" <= r.get("end", "") <= "2025-12-31"
        and 330 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 380
    ]
    if not rows:
        return [dict(symbol=symbol, status="no_annual_cash_paid_tag")]
    results = []
    for end in sorted({r["end"] for r in rows}):
        candidates = [r for r in rows if r["end"] == end]
        first = min(candidates, key=lambda r: (r["filed"], r["accn"]))
        same = [
            r for r in candidates if r["filed"] == first["filed"] and r["accn"] == first["accn"]
        ]
        out = dict(
            symbol=symbol,
            fiscal_end=end,
            source_tag=TAG,
            source_unit="USD/shares",
            sources=same,
            status="unresolved",
            events_verified=False,
        )
        if len({(r["start"], Decimal(str(r["val"]))) for r in same}) != 1:
            results.append(dict(out, status="filing_value_or_period_conflict"))
            continue
        start = first["start"]
        if start < "2021-08-01":
            results.append(dict(out, status="left_coverage_gap"))
            continue
        selected = [
            e for e in events if e["symbol"] == symbol and start <= e.get("payable_date", "") <= end
        ]
        if not selected:
            results.append(dict(out, status="no_supplier_events"))
            continue
        reported = Decimal(str(first["val"]))
        total = sum((Decimal(str(e["rate"])) for e in selected), Decimal(0))
        diff = total - reported
        duplicates = Counter((e["symbol"], e["ex_date"]) for e in selected)
        status = (
            "exact_numeric_match"
            if abs(diff) <= Decimal("1e-10")
            else "within_one_cent"
            if abs(diff) <= Decimal(".01")
            else "amount_discrepancy"
        )
        results.append(
            dict(
                out,
                status=status,
                start=start,
                sec_per_share=str(reported),
                supplier_sum=str(total),
                difference=str(diff),
                supplier_to_sec=float(total / reported) if reported else None,
                events=selected,
                duplicate_ex_dates=[k[1] for k, v in duplicates.items() if v > 1],
                has_special_or_foreign=any(e.get("special") or e.get("foreign") for e in selected),
            )
        )
    return results


def main():
    source = ROOT / "2026-09-22-dividend-audit.json"
    provider = json.loads(source.read_text())
    hashes = {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}
    rows = []
    for symbol in provider["symbols"]:
        path = Path("artifacts/research/sec-quality") / f"{symbol}-facts.json"
        if not path.exists():
            path = Path("artifacts/research/transfer12-sec") / f"{symbol}-facts.json"
        if not path.exists():
            rows.append(dict(symbol=symbol, status="missing_sec_file"))
            continue
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.extend(audit(symbol, json.loads(path.read_text()), provider["events"]))
    out = dict(
        status="completed",
        source_hashes=hashes,
        results=rows,
        counts=dict(Counter(r["status"] for r in rows)),
        scope=(
            "Retrospective accounting comparison; "
            "no historical availability or event completeness guarantee"
        ),
    )
    (ROOT / "2026-09-22-dividend-sec.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    )
    print(out["counts"])
    for r in rows:
        if r["status"] == "amount_discrepancy":
            print(
                r["symbol"],
                r["fiscal_end"],
                r["sec_per_share"],
                r["supplier_sum"],
                r["supplier_to_sec"],
            )


if __name__ == "__main__":
    main()
