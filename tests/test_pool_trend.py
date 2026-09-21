"""Aggregate exposure gates cannot use future prices or renormalize cash away."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_pool_trend import forecasts  # noqa: E402


def test_gates_are_causal_and_reduce_target_budget():
    rng = np.random.default_rng(47)
    prices = 100 * np.exp(rng.normal(0, 0.02, (215, 8)).cumsum(axis=0))
    f = pd.DataFrame(
        [
            dict(day=f"{i:03d}", symbol=str(j), close=prices[i, j])
            for i in range(215)
            for j in range(8)
        ]
    )
    before, _ = forecasts(f)
    f.loc[f.day > "207", "close"] *= 4
    after, _ = forecasts(f)
    for mode in before:
        for key, value in before[mode].items():
            assert value["target_weight"] <= before["equal"][key]["target_weight"] + 1e-12
            if key[0] <= "207":
                assert value == after[mode][key]
