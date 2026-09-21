"""Financial growth/profitability can be computed without future amendments."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gross_investment_features import judge  # noqa: E402


def test_published_annual_financial_ratios():
    base = dict(
        start="2023-01-01", end="2023-12-31", filed="2024-02-01", form="10-K", accn="old", val=40
    )
    asset = {k: v for k, v in base.items() if k != "start"}
    asset["val"] = 200
    facts = {
        "facts": {
            "us-gaap": {
                "GrossProfit": {
                    "units": {"USD": [base, {**base, "filed": "2025-02-01", "val": 4000}]}
                },
                "Assets": {"units": {"USD": [asset, {**asset, "end": "2022-12-31", "val": 100}]}},
            }
        }
    }
    r = judge(facts, "2024-03-01", "AAPL")
    assert r["gross"] == 0.2 and r["growth"] == 1
    assert r["status"] == "证据不足"
    assert not judge(facts, "2026-03-01", "AAPL").get("candidate_eligible")
