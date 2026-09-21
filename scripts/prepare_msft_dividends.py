"""Read issuer-linked Microsoft dividend workbook without inferred Excel formulas."""

import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path("docs/research-results")
SOURCE = Path("artifacts/research/issuer-dividends/msft-history.xlsx")
URL = "https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/Microsofts-Dividend-History"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def main():
    with zipfile.ZipFile(SOURCE) as z:
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        assert workbook.find("m:workbookPr", NS).get("date1904", "0") in ("0", "false")
        strings = [
            "".join(t.text or "" for t in si.findall(".//m:t", NS))
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)
        ]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row in sheet.findall("m:sheetData/m:row", NS):
            cells = {}
            for c in row:
                if c.find("m:f", NS) is not None:
                    raise ValueError("Formula in source table")
                v = c.find("m:v", NS)
                if v is not None:
                    cells[c.get("r").rstrip("0123456789")] = (
                        strings[int(v.text)] if c.get("t") == "s" else v.text
                    )
            rows.append(cells)
        assert [rows[0].get(k) for k in "ABCDEF"] == [
            "Dividend Period",
            "Amount",
            "Announcement Date",
            "Ex-Dividend Date",
            "Record Date",
            "Payable Date",
        ]
    facts_path = Path("artifacts/research/sec-quality/MSFT-facts.json")
    fact = json.loads(facts_path.read_text())["facts"]["us-gaap"][
        "CommonStockDividendsPerShareDeclared"
    ]
    assert "USD/shares" in fact["units"]
    events = []
    for row in rows[1:]:
        if not all(k in row for k in "ABCDEF"):
            continue

        def excel_date(value):
            n = Decimal(value)
            assert n == int(n) and n > 60
            return (date(1899, 12, 30) + timedelta(days=int(n))).isoformat()

        announcement, ex, record, pay = [excel_date(row[k]) for k in "CDEF"]
        if not "2021-08-01" <= ex < "2026-09-01":
            continue
        source_amount = Decimal(row["B"])
        amount = source_amount.quantize(Decimal("0.01"))
        # The issuer worksheet formats dollar amounts to two decimals.
        assert abs(source_amount - amount) < Decimal("1e-12")
        assert announcement < ex <= record <= pay and amount > 0
        events.append(
            dict(
                id="MSFT-issuer-" + ex,
                symbol="MSFT",
                rate=str(amount),
                source_cell_numeric=row["B"],
                announcement_date=announcement,
                ex_date=ex,
                record_date=record,
                payable_date=pay,
                kind="ordinary_cash",
                amount_basis="gross",
                currency="USD",
                verified=True,
                evidence=[
                    URL,
                    "SEC companyfacts MSFT CommonStockDividendsPerShareDeclared USD/shares",
                ],
                historical_provider_visibility_verified=False,
            )
        )
    events.sort(key=lambda e: e["ex_date"])
    assert len({e["ex_date"] for e in events}) == len(events)
    supplier = json.loads((ROOT / "2026-09-22-dividend-audit.json").read_text())["events"]
    comparison = []
    for e in events:
        matches = [r for r in supplier if r["symbol"] == "MSFT" and r["ex_date"] == e["ex_date"]]
        comparison.append(
            dict(
                ex_date=e["ex_date"],
                supplier_records=len(matches),
                matching_amount_record_payment=len(matches) == 1
                and Decimal(str(matches[0]["rate"])) == Decimal(e["rate"])
                and matches[0]["record_date"] == e["record_date"]
                and matches[0]["payable_date"] == e["payable_date"],
                supplier=matches,
            )
        )
    out = dict(
        status="completed",
        events=events,
        comparison=comparison,
        source_url=URL,
        issuer_link_page="https://www.microsoft.com/en-us/investor/dividends-and-stock-history",
        source_hashes={
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [SOURCE, facts_path, Path("artifacts/research/issuer-dividends/source-1.html")]
        },
        caveat=(
            "Issuer current historical table and announcement dates; "
            "not archived vendor first-visibility data or tax/account cash receipts"
        ),
    )
    (ROOT / "2026-09-22-msft-dividends.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    )
    print(
        len(events),
        "issuer events",
        sum(x["matching_amount_record_payment"] for x in comparison),
        "exact supplier matches",
    )


if __name__ == "__main__":
    main()
