"""Projection KKT conditions and causal online allocation."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_olmar import forecasts, project_capped, update  # noqa: E402


def test_projection_constraints_and_stationarity():
    x = np.array([0.4, 0.3, 0.2, 0.1, 0.0, -0.1])
    w = project_capped(x, 0.25)
    assert abs(w.sum() - 1) < 1e-10
    assert w.min() >= 0 and w.max() <= 0.25
    interior = (w > 1e-9) & (w < 0.25 - 1e-9)
    offset = x - w
    np.testing.assert_allclose(offset[interior], offset[interior][0], atol=1e-10)
    assert np.all(offset[w == 0] <= offset[interior][0] + 1e-10)
    assert np.all(offset[w == 0.25] >= offset[interior][0] - 1e-10)
    b = np.ones(10) / 10
    np.testing.assert_array_equal(update(b, np.ones(10)), b)


def test_future_bars_do_not_change_past_targets():
    rng = np.random.default_rng(4)
    prices = 100 * np.exp(rng.normal(0, 0.01, (75, 10)).cumsum(axis=0))
    frame = pd.DataFrame(
        [
            dict(day=f"{i:03d}", symbol=str(j), close=prices[i, j])
            for i in range(75)
            for j in range(10)
        ]
    )
    before = forecasts(frame)
    frame.loc[frame.day > "069", "close"] *= 2
    after = forecasts(frame)
    for method in before:
        for key, value in before[method].items():
            if key[0] <= "069":
                assert value == after[method][key]
