"""Check the economic distinction and causal construction, without tuning returns."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from information_continuity import forecasts, path_metrics  # noqa: E402


def test_equal_cumulative_return_different_path_and_zero_denominator():
    pret, identity = path_metrics(np.array([[0.01, -0.01, 0], [0.01, -0.01, 0], [0.01, 0.05, 0]]))
    np.testing.assert_allclose(pret, [0.03, 0.03, 0])
    np.testing.assert_allclose(identity, [-1, 1 / 3, 0])
    _, identity = path_metrics(np.array([[0.02], [0], [0], [0.01]]))
    np.testing.assert_allclose(identity, [-0.5])


def test_future_changes_and_price_units_do_not_change_past_decisions():
    rng = np.random.default_rng(814)
    values = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.009, (340, 6)), axis=0))
    prices = pd.DataFrame(
        values,
        index=pd.bdate_range("2023-01-02", periods=340).strftime("%Y-%m-%d"),
        columns=list("ABCDEF"),
    )
    frame = (
        prices.rename_axis("day")
        .reset_index()
        .melt(id_vars="day", var_name="symbol", value_name="close")
    )
    start, cutoff, end = prices.index[260], prices.index[310], "2025-01-01"
    full, ds, _ = forecasts(frame, start, end)
    prefix, _, _ = forecasts(frame[frame.day < cutoff], start, cutoff)
    scaled = frame.copy()
    scaled["close"] *= 7
    other, other_ds, _ = forecasts(scaled, start, end)
    assert [d["selected"] for d in ds] == [d["selected"] for d in other_ds]
    for method in full:
        assert {k: v for k, v in full[method].items() if k[0] < cutoff} == prefix[method]
        np.testing.assert_allclose(
            [v["target_weight"] for v in full[method].values()],
            [v["target_weight"] for v in other[method].values()],
            rtol=1e-10,
            atol=1e-12,
        )
