"""Reconcile supplier LIN dividends with issuer table; preserve unresolved ex-date/tax scope."""

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path("docs/research-results")
CACHE = Path("artifacts/research/dividend-audit")


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def main():
    source = CACHE / "linde-followup-1.html"
    parser = TableRows()
    parser.feed(source.read_text())
    assert parser.rows[0] == ["Declaration Date", "Record Date", "Payable Date", "Amount Per Share"]
    declarations = []
    for row in parser.rows:
        if len(row) != 4 or not all(re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", v) for v in row[:3]):
            continue
        if not re.fullmatch(r"\$\s*\d+(?:\.\d+)?", row[3]):
            continue
        dates = [datetime.strptime(v, "%m/%d/%Y").date().isoformat() for v in row[:3]]
        declarations.append(
            dict(
                declaration_date=dates[0],
                record_date=dates[1],
                payable_date=dates[2],
                rate=str(Decimal(row[3].replace("$", "").strip())),
            )
        )
    if not declarations:
        raise ValueError("Issuer table format changed")
    supplier = json.loads((ROOT / "2026-09-22-dividend-audit.json").read_text())
    events = [e for e in supplier["events"] if e["symbol"] == "LIN"]
    rows = []
    for event in events:
        matches = [
            d
            for d in declarations
            if d["payable_date"] == event["payable_date"]
            and d["record_date"] == event["record_date"]
            and Decimal(d["rate"]) == Decimal(str(event["rate"]))
        ]
        active = event["cusip"] == "G54950103" if event["ex_date"] >= "2023-03-01" else None
        same_record = [
            d
            for d in declarations
            if d["record_date"] == event["record_date"]
            and Decimal(d["rate"]) == Decimal(str(event["rate"]))
        ]
        rows.append(
            dict(
                source_id=event["id"],
                cusip=event["cusip"],
                ex_date=event["ex_date"],
                payable_date=event["payable_date"],
                rate=event["rate"],
                issuer_matches=matches,
                issuer_record_amount_matches=same_record,
                payment_date_conflict=bool(same_record and not matches),
                active_security_after_reorganization=active,
                economic_event_key=[
                    "LIN",
                    event["record_date"],
                    event["payable_date"],
                    str(Decimal(str(event["rate"]))),
                ],
                ex_date_independently_verified=False,
                book_ready=False,
            )
        )
    facts = json.loads((CACHE.parent / "transfer12-sec/LIN-facts.json").read_text())
    units = facts["facts"]["us-gaap"]["CommonStockDividendsPerShareCashPaid"]["units"]["USD/shares"]
    q1 = [
        r
        for r in units
        if r.get("start") == "2023-01-01"
        and r.get("end") == "2023-03-31"
        and r["filed"] == "2023-04-27"
    ]
    assert len(q1) == 1 and q1[0]["val"] == 1.275
    duplicate = [r for r in rows if r["ex_date"] == "2023-03-13"]
    assert len(duplicate) == 2 and all(len(r["issuer_matches"]) == 1 for r in duplicate)
    selected = [r for r in duplicate if r["active_security_after_reorganization"]]
    assert len(selected) == 1
    out = dict(
        status="completed",
        declarations=declarations,
        reconciliation=rows,
        issuer_quarterly_usd_per_share_evidence=q1[0],
        duplicate_resolution=dict(
            canonical_event=selected[0],
            source_ids=[r["source_id"] for r in duplicate],
            total_gross_per_share="1.275",
            not_sum_of_source_rows=True,
            scope=(
                "Declaration amount/payment and active security resolved; "
                "ex-date/tax/data-availability still separate"
            ),
        ),
        source_hashes={
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                source,
                CACHE / "linde-followup-2.html",
                CACHE / "linde-8937.pdf",
                CACHE.parent / "transfer12-sec/LIN-facts.json",
            ]
        },
    )
    (ROOT / "2026-09-22-linde-dividend-reconciliation.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    )
    print(
        len(declarations),
        "issuer rows",
        len(rows),
        "supplier events",
        sum(len(r["issuer_matches"]) == 1 for r in rows),
        "matched",
    )
    print("2023-03 duplicate: one gross distribution of USD 1.275 per share; not USD 2.55")


if __name__ == "__main__":
    main()
