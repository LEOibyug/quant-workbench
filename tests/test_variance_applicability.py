"""Variance-ratio formula reference and unit invariance."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from variance_applicability import judge_returns  # noqa: E402


def test_robust_statistic_matches_explicit_sums():
    r = np.random.default_rng(17).normal(0, 0.01, 126)
    e = r - r.mean()
    total = sum(float(v * v) for v in e)
    vr = sum(sum(e[i : i + 5]) ** 2 for i in range(122)) / (5 * 122 * (1 - 5 / 126)) / (total / 125)
    theta = sum(
        (2 * (5 - j) / 5) ** 2 * sum(e[t] ** 2 * e[t - j] ** 2 for t in range(j, 126)) / total**2
        for j in range(1, 5)
    )
    result = judge_returns(r)
    assert result["variance_ratio"] == pytest.approx(vr)
    assert result["z"] == pytest.approx((vr - 1) / np.sqrt(theta))
    assert judge_returns(r * 10 + 0.2)["z"] == pytest.approx(result["z"])
    assert judge_returns(np.zeros(126))["candidate"] == "cash"
    assert "z" not in judge_returns(r[:100])
