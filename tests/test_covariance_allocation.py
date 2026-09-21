"""Analytical portfolio optima and risk constraints."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_covariance_allocation import allocate  # noqa: E402


def test_diagonal_covariance_matches_analytic_optima():
    sigma = np.linspace(0.004, 0.006, 10)
    cov = np.diag(sigma**2)
    for method, raw in [("minimum_variance", 1 / sigma**2), ("maximum_diversification", 1 / sigma)]:
        weights, ok = allocate(cov, method)
        assert ok
        np.testing.assert_allclose(weights, 0.95 * raw / raw.sum(), atol=2e-5)


def test_risk_budget_and_concentration():
    cov = np.eye(10) * 0.1**2 + np.ones((10, 10)) * 0.05**2
    for method in ("minimum_variance", "maximum_diversification", "equal_risk_scaled"):
        weights, ok = allocate(cov, method)
        assert ok
        assert min(weights) >= 0 and max(weights) <= 0.2
        assert sum(weights) <= 0.95 + 1e-8
        assert np.sqrt(weights @ cov @ weights * 252) <= 0.1 + 1e-8
