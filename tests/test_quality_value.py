import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from quality_value_features import judge


def facts():
    tags = {}
    for tag, values, unit in [
        ("Assets", [1000, 1100, 1200], "USD"),
        ("NetIncomeLoss", [100, 120, 150], "USD"),
        ("NetCashProvidedByUsedInOperatingActivities", [120, 140, 180], "USD"),
        ("WeightedAverageNumberOfDilutedSharesOutstanding", [10, 10, 10], "shares"),
    ]:
        tags[tag] = {
            "units": {
                unit: [
                    dict(
                        start=f"{y}-01-01",
                        end=f"{y}-12-31",
                        filed=f"{y + 1}-02-10",
                        form="10-K",
                        val=v,
                        accn=str(y),
                    )
                    for y, v in zip([2022, 2023, 2024], values, strict=True)
                ]
            }
        }
    return {"facts": {"us-gaap": tags}}


def test_quality_value_is_scale_consistent_and_no_future_shares():
    f = facts()
    a = judge(f, "2025-09-01", "TEST", 100.0)
    assert a["candidate_pass"] and a["earnings_yield"] == pytest.approx(0.15)
    b = judge(f, "2025-09-01", "TEST", 200.0)
    assert b["quality"] == a["quality"] and b["earnings_yield"] == a["earnings_yield"] / 2
    shares = f["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"][
        "shares"
    ]
    shares.append({**shares[-1], "val": 1000, "filed": "2025-09-02"})
    assert judge(f, "2025-09-01", "TEST", 100.0) == a
    assert judge(f, "2025-09-02", "TEST", 100.0)["earnings_yield"] == a["earnings_yield"]


def test_outside_domain_stale_and_missing_data_are_not_suitability():
    for result in [
        judge(facts(), "2025-09-01", "JPM", 100.0),
        judge(facts(), "2027-09-01", "TEST", 100.0),
        judge({"facts": {}}, "2025-09-01", "TEST", 100.0),
    ]:
        assert result["status"] == "证据不足" and not result.get("candidate_pass")
