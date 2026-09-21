"""Missing issuance and later disclosures must never manufacture positive payout."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_payout_data import TAGS, judge  # noqa: E402


def test_missing_and_future_issuance_are_not_zero():
    base = dict(
        start="2023-01-01", end="2023-12-31", filed="2024-02-01", form="10-K", accn="one", val=10
    )
    facts = {"facts": {"us-gaap": {t: {"units": {"USD": [dict(base)]}} for t in TAGS.values()}}}
    result = judge(facts, "TEST", "2024-09-01")
    assert result["cash_net_payout_usd"] == 10
    assert result["status"] == "证据不足"
    missing = copy.deepcopy(facts)
    del missing["facts"]["us-gaap"][TAGS["issuance"]]
    assert "cash_net_payout_usd" not in judge(missing, "TEST", "2024-09-01")
    future = copy.deepcopy(facts)
    future["facts"]["us-gaap"][TAGS["issuance"]]["units"]["USD"][0]["filed"] = "2024-09-01"
    assert "cash_net_payout_usd" not in judge(future, "TEST", "2024-09-01")
    future["facts"]["us-gaap"][TAGS["issuance"]]["units"]["USD"][0]["filed"] = "2025-01-01"
    assert "cash_net_payout_usd" not in judge(future, "TEST", "2024-09-01")
