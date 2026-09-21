"""Different annual periods must not be subtracted to form an accrual score."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from accrual_features import judge  # noqa: E402


def test_matching_fiscal_periods_required():
    row = dict(start="2023-01-01", end="2023-12-31", filed="2024-02-15", form="10-K", val=100)
    cash = {**row, "val": 120}
    asset = {k: v for k, v in row.items() if k != "start"}
    asset["val"] = 400
    facts = {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {"units": {"USD": [row]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [cash]}},
                "Assets": {"units": {"USD": [asset, {**asset, "end": "2022-12-31"}]}},
            }
        }
    }
    assert judge(facts, "2024-03-01", "AAPL")["score"] == -0.05
    cash["start"] = "2023-02-01"
    result = judge(facts, "2024-03-01", "AAPL")
    assert result["status"] == "证据不足" and not result.get("candidate_eligible")
