"""Causal features and exact forward-label boundary, without full training."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from learned_applicability import feature, utility_label  # noqa: E402


def test_features_do_not_use_future():
    rng = np.random.default_rng(12)
    logs = rng.normal(size=(110, 2)).cumsum(axis=0)
    weights = rng.uniform(size=(110, 2, 3))
    before = feature(logs, weights, 70, 0)
    logs[71:] = -1000
    weights[71:] = 0
    np.testing.assert_array_equal(before, feature(logs, weights, 70, 0))


def test_label_uses_exact_maturity_and_round_trip_fee():
    opens = np.ones((40, 1)) * 100
    weights = np.zeros((40, 1, 3))
    weights[:, :, 0] = 1
    assert utility_label(opens, weights, 0, 0) == 0
    opens[22:] = 110
    assert utility_label(opens, weights, 0, 0) == 1
    opens[23:] = 1
    assert utility_label(opens, weights, 0, 0) == 1


def test_judgment_rejects_missing_and_training_period_data():
    import pandas as pd
    from judge_learned_applicability import judge

    empty = pd.DataFrame(columns=["day", "symbol", "open", "close"])
    assert judge(empty, "ACN", "2026-08-31")["status"] == "证据不足"
    prices = pd.DataFrame([dict(day="2024-01-02", symbol="ACN", open=100, close=101)])
    assert "更早" in judge(prices, "ACN", "2024-01-02")["reasons"][0]
    assert "不足64" in judge(prices, "ACN", "2026-08-31")["reasons"][0]
