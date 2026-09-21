import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from study_state_gate import judge


def prices():
    return pd.DataFrame(
        dict(
            day=pd.bdate_range("2024-01-01", periods=150).strftime("%Y-%m-%d"),
            close=np.linspace(100, 160, 150),
            volume=1000000,
        )
    )


def test_gate_excludes_future_observations_and_is_not_validated():
    frame = prices()
    day = frame.day.iloc[126]
    before = judge(frame, day, require_quality=False)
    frame.loc[frame.day > day, "close"] = 1
    assert judge(frame, day, require_quality=False) == before
    assert before["candidate_status"] == "通过"
    assert before["status"] == "证据不足"
    assert judge(frame.iloc[:126], day, require_quality=False)["candidate_status"] == "证据不足"


def test_missing_financials_and_downtrend_are_distinct():
    frame = prices()
    assert judge(frame, frame.day.iloc[-1])["candidate_status"] == "证据不足"
    frame["close"] = frame.close.iloc[::-1].to_numpy()
    result = judge(frame, frame.day.iloc[-1], require_quality=False)
    assert result["candidate_status"] == "未通过"
    assert any(not c["passed"] for c in result["checks"])
