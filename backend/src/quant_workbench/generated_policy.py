"""Frozen synthetic-trained strategy classifier. No training during simulation."""

import hashlib
import os
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

from quant_workbench.synthetic_regimes import window_features

ARTIFACT = Path(
    os.getenv("QUANT_GENERATED_POLICY", "artifacts/models/generated-policy-v1/classifier.joblib")
)


@lru_cache(maxsize=4)
def _load(path, modified):
    return joblib.load(path)


def policy_probabilities(log_prices):
    if not ARTIFACT.is_file():
        raise ValueError("生成策略分类器尚未训练，请运行 scripts/train_generated_policy.py")
    bundle = _load(str(ARTIFACT.resolve()), ARTIFACT.stat().st_mtime_ns)
    p = bundle["model"].predict_proba(window_features(log_prices).reshape(1, -1))[0]
    result = np.zeros(3)
    result[bundle["model"].classes_.astype(int)] = p
    return result, bundle["version"]


def artifact_digest():
    if not ARTIFACT.is_file():
        raise ValueError("生成策略分类器尚未训练，请运行 scripts/train_generated_policy.py")
    return hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()
