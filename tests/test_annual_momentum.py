"""Signal invariance to future data, row order, and nominal price units."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_annual_momentum import forecasts  # noqa: E402


def test_causal_unit_invariant_targets():
    rng = np.random.default_rng(62)
    p = 100 * np.exp(rng.normal(0.001, 0.01, (270, 10)).cumsum(axis=0))
    frame = pd.DataFrame(
        [dict(day=f"{i:03d}", symbol=str(j), close=p[i, j]) for i in range(270) for j in range(10)]
    )
    first = forecasts(frame)
    modified = frame.copy()
    modified.loc[modified.day > "260", "close"] *= 3
    modified.loc[modified.symbol == "0", "close"] *= 100
    second = forecasts(modified.sample(frac=1, random_state=3))
    for method, rows in first.items():
        for key, row in rows.items():
            if key[0] <= "260":
                np.testing.assert_allclose(
                    row["target_weight"], second[method][key]["target_weight"], atol=1e-10
                )
