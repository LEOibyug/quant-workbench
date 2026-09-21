"""Market adjustment must preserve idiosyncratic drift rather than OLS zero-sum."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_idiosyncratic_momentum import adjusted_score  # noqa: E402


def test_shared_factor_removal_preserves_opposite_drifts():
    t = np.arange(252)
    market = 0.02 * np.sin(t * 0.3)
    residual = 0.002 * np.cos(t * 0.73)
    # Orthogonalize noise so the common-factor slope has an exact reference.
    design = np.column_stack([np.ones(252), market])
    residual -= design @ np.linalg.lstsq(design, residual, rcond=None)[0]
    h = np.column_stack([market + 0.001 + residual, market - 0.001 - residual])
    scores = adjusted_score(h)
    assert scores[0] > 0 and scores[1] < 0
    np.testing.assert_allclose(scores[0], -scores[1], atol=1e-10)
    np.testing.assert_allclose(scores, adjusted_score(h * 10), atol=1e-10)
