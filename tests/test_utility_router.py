"""Negative utility implies cash; resampling preserves adjacent date groups."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from utility_router import block_indices, choices  # noqa: E402


def test_cash_rejection_and_block_geometry():
    np.testing.assert_array_equal(
        choices(np.array([[-0.1, -0.2, -0.3], [0, 0, 0], [0.1, 0.3, 0.2]])), [0, 0, 2]
    )
    selected = block_indices(41, np.random.default_rng(3))
    assert len(selected) == 41 and selected.min() >= 0 and selected.max() < 41
    for start in range(0, len(selected), 3):
        assert np.all(np.diff(selected[start : start + 3]) == 1)
