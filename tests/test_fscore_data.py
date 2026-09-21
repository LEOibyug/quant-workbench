"""Financial restatements and missing offering evidence cannot leak into a score."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_fscore_data import observations  # noqa: E402


def test_later_filing_and_same_day_filing_are_excluded():
    old = dict(start="2023-01-01", end="2023-12-31", filed="2024-02-01", form="10-K", val=100)
    future = {**old, "filed": "2025-03-01", "form": "10-K/A", "val": 999}
    facts = {"facts": {"us-gaap": {"Revenue": {"units": {"USD": [old, future]}}}}}
    assert observations(facts, ["Revenue"], "2025-03-01", True)["2023-12-31"]["val"] == 100
    assert observations(facts, ["Revenue"], "2025-03-02", True)["2023-12-31"]["val"] == 999
    assert observations(facts, ["Missing"], "2025-03-02", True) == {}
