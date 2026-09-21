"""Forward probabilities cannot depend on future observations."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from regime_router import forward  # noqa: E402


def test_forward_is_normalized_and_prefix_causal():
    rng = np.random.default_rng(41)
    likelihood = np.exp(rng.normal(size=(20, 5, 3)))
    initial = np.array([0.2, 0.3, 0.5])
    transition = np.array([[0.8, 0.1, 0.1], [0.2, 0.6, 0.2], [0.1, 0.1, 0.8]])
    full = forward(likelihood, initial, transition)
    prefix = forward(likelihood[:12], initial, transition)
    np.testing.assert_allclose(full.sum(axis=2), 1)
    np.testing.assert_array_equal(full[:12], prefix)
    assert (full >= 0).all()
