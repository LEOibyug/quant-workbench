"""Fixed ridge utility models and block-bootstrap instability proxy."""

import numpy as np


def route_scores(bundle, features, mode):
    x = bundle["scaler"].transform(features)
    if mode == "constant":
        return np.broadcast_to(bundle["mean_utility"], (len(x), 3)).copy()
    if mode == "mean":
        return bundle["model"].predict(x)
    if mode == "lower":
        return np.quantile(
            np.stack([model.predict(x) for model in bundle["bootstrap"]]), 0.1, axis=0
        )
    raise ValueError(mode)


def choices(scores):
    best = scores.argmax(axis=1)
    return np.where(scores[np.arange(len(scores)), best] > 0, best + 1, 0)


def block_indices(groups, rng):
    starts = rng.integers(0, groups - 2, size=int(np.ceil(groups / 3)))
    return np.concatenate([np.arange(s, s + 3) for s in starts])[:groups]
