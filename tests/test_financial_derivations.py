"""Derived accounting identity must match filing, period and public availability."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_financial_derivations import enrich  # noqa: E402


def test_gross_profit_derivation_rejects_mixed_filings_and_future_cost():
    row = dict(
        start="2023-01-01",
        end="2023-12-31",
        filed="2024-02-01",
        form="10-K",
        accn="filing-1",
        val=100,
    )
    cost = {**row, "val": 60}
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [row]}},
                "CostOfRevenue": {"units": {"USD": [cost]}},
            }
        }
    }
    enriched, audit = enrich(facts, "2024-03-01")
    derived = enriched["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"][0]
    assert derived["val"] == 40 and audit[0]["status"] == "derived"
    assert "GrossProfit" not in facts["facts"]["us-gaap"]
    cost["accn"] = "other-filing"
    assert "GrossProfit" not in enrich(facts, "2024-03-01")[0]["facts"]["us-gaap"]
    cost["accn"] = "filing-1"
    cost["filed"] = "2024-03-01"
    assert "GrossProfit" not in enrich(facts, "2024-03-01")[0]["facts"]["us-gaap"]
