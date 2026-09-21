import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from study_dual_class import screen


def sample():
    rng = np.random.default_rng(49)
    spread = np.zeros(160)
    for i in range(1, 160):
        spread[i] = 0.85 * spread[i - 1] + rng.normal(0, 0.008)
    dates = pd.bdate_range("2024-01-01", periods=160).strftime("%Y-%m-%d")
    return pd.concat(
        [
            pd.DataFrame(dict(day=dates, symbol=s, close=p, volume=1000000))
            for s, p in [("A", 100 * np.exp(spread)), ("B", np.full(160, 100.0))]
        ],
        ignore_index=True,
    )


def test_spread_screen_excludes_future_and_is_symmetric():
    frame = sample()
    day = sorted(frame.day.unique())[140]
    before = screen(frame, day, "A", "B")
    after = frame.copy()
    after.loc[after.day > day, "close"] = 1
    assert screen(after, day, "A", "B") == before
    flipped = screen(frame, day, "B", "A")
    assert flipped["z"] == pytest.approx(-before["z"])
    assert flipped["half_life"] == pytest.approx(before["half_life"])
    assert before["status"] == "证据不足"
    assert before["window_end"] < day


def test_insufficient_history_and_constant_spread_are_not_entries():
    frame = sample()
    early = sorted(frame.day.unique())[100]
    assert screen(frame, early, "A", "B")["candidate_status"] == "证据不足"
    frame["close"] = 100.0
    result = screen(frame, max(frame.day), "A", "B")
    assert result["candidate_status"] == "未通过"
    assert not result["entry_signal"]


def test_joint_pair_ledger_and_liquidity_rejection():
    from trade_dual_class import trade

    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    frame = pd.concat(
        [
            pd.DataFrame(dict(day=days, symbol=s, open=p, close=p, volume=100000000))
            for s, p in [("A", [110.0, 110.0, 100.0, 100.0]), ("B", [100.0] * 4)]
        ],
        ignore_index=True,
    )
    decisions = {
        ("A", d): dict(
            candidate_status="通过", entry_signal=i == 0, displacement=float(np.log(1.1)), z=2.0
        )
        for i, d in enumerate(days)
    }
    normal = trade(frame, decisions, "A", "B", "2024-01-02", "2024-01-06", 1)
    double = trade(frame, decisions, "A", "B", "2024-01-02", "2024-01-06", 2)
    assert normal["entries"] == normal["exits"] == 1
    assert not normal["open_position"] and normal["return_pct"] > 0
    assert double["return_pct"] < normal["return_pct"]
    frame["volume"] = 1
    illiquid = trade(frame, decisions, "A", "B", "2024-01-02", "2024-01-06", 1)
    assert illiquid["entries"] == 0 and illiquid["return_pct"] == 0
