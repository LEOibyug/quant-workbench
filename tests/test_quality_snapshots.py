import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "quality_snapshot", Path(__file__).parents[1] / "scripts/build_quality_snapshots.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_annual_values_respect_filing_time_and_future_restatement():
    rows = [
        dict(
            start="2023-01-01", end="2023-12-31", filed="2024-02-01", form="10-K", val=100, accn="a"
        ),
        dict(
            start="2023-01-01", end="2023-12-31", filed="2025-02-01", form="10-K", val=10, accn="b"
        ),
        dict(
            start="2024-01-01", end="2024-03-31", filed="2024-05-01", form="10-K", val=99, accn="c"
        ),
    ]
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": rows}}}}}
    early = module.annual_values(facts, "net_income", "2024-09-01")
    assert len(early) == 1 and early[0]["val"] == 100
    assert module.annual_values(facts, "net_income", "2025-02-01")[0]["val"] == 100
    assert module.annual_values(facts, "net_income", "2025-02-02")[0]["val"] == 10


def test_missing_fundamentals_are_not_positive_quality():
    result = module.snapshot({"facts": {}}, {}, "2025-09-01")
    assert result["annual"] == []
    assert not result["complete_three_years"]
    assert not result["positive_income_and_cashflow_three_years"]
    assert result["gross_profit_assets_latest"] is None
