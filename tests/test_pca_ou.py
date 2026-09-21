"""Hedge basis invariance and no future influence on PCA signal state."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_pca_ou import factors_and_scores, forecasts, neutralize  # noqa: E402


def test_hedge_is_factor_basis_invariant():
    rng = np.random.default_rng(5)
    beta = rng.normal(size=(10, 3))
    weights = rng.normal(size=10)
    rotation = np.linalg.qr(rng.normal(size=(3, 3)))[0]
    w = neutralize(weights, beta)
    np.testing.assert_allclose(w @ beta, 0, atol=1e-12)
    np.testing.assert_allclose(w, neutralize(weights, beta @ rotation), atol=1e-12)
    scores, _, count = factors_and_scores(np.zeros((252, 10)))
    assert np.isnan(scores).all() and count == 0


def test_pca_targets_are_causal():
    rng = np.random.default_rng(6)
    p = 100 * np.exp(rng.normal(0, 0.01, (265, 8)).cumsum(axis=0))
    f = pd.DataFrame(
        [dict(day=f"{i:03d}", symbol=str(j), close=p[i, j]) for i in range(265) for j in range(8)]
    )
    before, _ = forecasts(f)
    f.loc[f.day > "258", "close"] *= 3
    after, _ = forecasts(f)
    for mode in before:
        assert {d: w for d, w in before[mode].items() if d <= "258"} == {
            d: w for d, w in after[mode].items() if d <= "258"
        }
