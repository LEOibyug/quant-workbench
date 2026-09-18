"""A frozen classifier trained only on synthetic processes, not market labels."""

from functools import lru_cache

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

LABELS = ("trend", "reversion", "noise")
VERSION = "synthetic-regimes-v1-seed-1709"


def window_features(log_prices):
    y = np.asarray(log_prices, dtype=float)
    r = np.diff(y)
    scale = max(float(r.std()), 1e-8)
    t = np.arange(len(y), dtype=float)
    slope = np.polyfit(t, y, 1)[0]

    def corr(a, b):
        return float(np.corrcoef(a, b)[0, 1]) if min(a.std(), b.std()) > 1e-10 else 0.0

    centered = y - y.mean()
    # Scale and level invariant; no ticker identity or calendar date as features.
    return np.array(
        [
            r.mean() / scale,
            abs(r.mean()) / scale,
            abs(y[-1] - y[0]) / max(np.abs(r).sum(), 1e-8),
            slope * np.sqrt(len(y)) / scale,
            corr(r[1:], r[:-1]),
            corr(r[5:], r[:-5]),
            (y[-1] - y.mean()) / max(y.std(), 1e-8),
            r[-21:].std() / scale,
            np.mean(np.sign(r[1:]) == np.sign(r[:-1])),
            centered.std() / max(scale * np.sqrt(len(y)), 1e-8),
            np.mean((r / scale) ** 3),
            min(100.0, np.mean((r / scale) ** 4)),
        ]
    )


def generated_windows(seed, per_class=800, shifted=False):
    rng = np.random.default_rng(seed)
    features = []
    labels = []
    for label in range(3):
        for _ in range(per_class):
            length = 64
            sigma = rng.uniform(0.003, 0.035)
            if label == 0:
                drift = (
                    rng.choice([-1, 1]) * sigma * rng.uniform(0.02, 0.25 if not shifted else 0.4)
                )
                innovations = rng.standard_t(6, size=length) * sigma
                returns = np.zeros(length)
                phi = rng.uniform(0, 0.35)
                for j in range(1, length):
                    returns[j] = drift + phi * returns[j - 1] + innovations[j]
                path = np.cumsum(returns)
            elif label == 1:
                phi = rng.uniform(0.65, 0.97) if not shifted else rng.uniform(0.85, 0.995)
                full = np.zeros(length + 256)
                for j in range(1, len(full)):
                    full[j] = phi * full[j - 1] + sigma * rng.standard_t(6)
                path = full[-length:]
            else:
                innovations = rng.standard_t(4 if shifted else 6, size=length) * sigma
                if rng.random() < 0.5:
                    innovations[length // 2 :] *= rng.uniform(0.5, 2.5)
                if rng.random() < 0.3:
                    innovations[rng.integers(length)] += sigma * rng.normal(0, 5)
                path = np.cumsum(innovations)
            features.append(window_features(path))
            labels.append(label)
    return np.array(features), np.array(labels)


@lru_cache(maxsize=1)
def classifier():
    x, y = generated_windows(1709)
    model = make_pipeline(
        StandardScaler(), LogisticRegression(C=1, max_iter=1000, random_state=1709)
    )
    model.fit(x, y)
    return model


def regime_probabilities(log_prices):
    return classifier().predict_proba(window_features(log_prices).reshape(1, -1))[0]
