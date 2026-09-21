import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from study_filing_drift import earnings_judge, quarter_observations


def sample():
    rows = []
    for year in range(2019, 2025):
        for quarter in (1, 2, 3):
            start = pd.Timestamp(year, 3 * quarter - 2, 1)
            end = start + pd.offsets.QuarterEnd()
            rows.append(
                dict(
                    start=str(start.date()),
                    end=str(end.date()),
                    filed=str((end + pd.Timedelta(days=40)).date()),
                    val=100 + (year - 2018) ** 2 * 10 + quarter,
                    form="10-Q",
                    accn=f"{year}-{quarter}",
                )
            )
    return {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": rows}}}}}


def test_income_signal_uses_filing_availability_and_no_lifetime_reset():
    facts = sample()
    records = quarter_observations(facts)
    base = earnings_judge(records, "2024-12-01")
    assert base["signal"] > 0 and base["quarter_end"] == "2024-09-30"
    assert base["first_filed"] < "2024-12-01"
    extra = {**records[-1], "filed": "2025-01-15", "val": 99999, "accn": "revision"}
    assert earnings_judge(records + [extra], "2024-12-01") == base
    assert earnings_judge(records + [extra], "2025-01-15") == base
    revised = earnings_judge(records + [extra], "2025-01-16")
    assert revised["first_filed"] == base["first_filed"]
    assert revised["source_filed"] == "2025-01-15"


def test_cumulative_quarter_and_insufficient_history_do_not_form_signal():
    facts = sample()
    data = facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]
    data.append(
        dict(
            start="2024-01-01",
            end="2024-09-30",
            filed="2024-11-09",
            val=999999,
            form="10-Q",
            accn="cumulative",
        )
    )
    records = quarter_observations(facts)
    assert not any(r["accn"] == "cumulative" for r in records)
    result = earnings_judge(records, "2020-06-01")
    assert result["status"] == "证据不足" and result["signal"] == 0
