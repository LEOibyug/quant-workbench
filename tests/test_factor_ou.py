"""Factor hedge algebra and causal residual targets."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_factor_ou import forecasts, hedge  # noqa: E402


def test_hedge_neutrality_survives_risk_scaling():
    beta = np.linspace(0.5, 1.5, 10)
    raw = np.linspace(-0.3, 0.5, 10)
    cov = np.eye(10) * 0.03**2
    w = hedge(raw, beta, cov, "beta_hedged")
    assert abs(w @ beta) < 1e-12
    assert abs(w).sum() <= 0.95 + 1e-12 and abs(w).max() <= 0.2 + 1e-12
    assert np.sqrt(w @ cov @ w * 252) <= 0.1 + 1e-12
    np.testing.assert_array_equal(hedge(raw, np.zeros(10), cov, "beta_hedged"), np.zeros(10))


def test_residual_state_is_causal():
    rng = np.random.default_rng(3)
    prices = 100 * np.exp(rng.normal(0, 0.02, (85, 8)).cumsum(axis=0))
    frame = pd.DataFrame(
        [
            dict(day=f"{i:03d}", symbol=str(j), close=prices[i, j])
            for i in range(85)
            for j in range(8)
        ]
    )
    before = forecasts(frame)
    frame.loc[frame.day > "074", "close"] *= 2
    after = forecasts(frame)
    for mode, days in before.items():
        assert {d: w for d, w in days.items() if d <= "074"} == {
            d: w for d, w in after[mode].items() if d <= "074"
        }
