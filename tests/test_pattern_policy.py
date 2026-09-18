import numpy as np
import pytest
from quant_workbench.conditional_policy import decompose


def test_pattern_decomposition_is_scale_invariant_and_not_target_as_input():
    rng = np.random.default_rng(22)
    path = np.cumsum(rng.normal(0.001, 0.015, 64))
    x, f, y = decompose(path)
    other, features, target = decompose(path * 3 + 9)
    np.testing.assert_allclose(x, other, atol=1e-5)
    np.testing.assert_allclose(f, features, atol=1e-5)
    np.testing.assert_allclose(y, target, atol=1e-5)
    assert x.shape == (4, 64) and f.shape == (10,) and y.shape == (3,)
    assert y.sum() == pytest.approx(1) and (y >= 0).all()
    assert not np.allclose(f[:3], y)


def test_known_patterns_and_constant_window_are_finite():
    for path in [np.ones(64), np.arange(64) * 0.01, np.sin(np.arange(64) * 2 * np.pi / 21)]:
        x, f, y = decompose(path)
        assert np.isfinite(x).all() and np.isfinite(f).all() and np.isfinite(y).all()
    assert decompose(np.arange(64) * 0.01)[2][0] > 0.99
    assert decompose(np.sin(np.arange(64) * 2 * np.pi / 21))[2][1] > 0.8
