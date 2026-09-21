"""Descriptive GMM regimes with causal filtering and frozen expert binding."""

import numpy as np
from quant_workbench.conditional_policy import decompose


def features(logs):
    output = []
    for i in range(63, len(logs)):
        rows = []
        for j in range(logs.shape[1]):
            window = logs[i - 63 : i + 1, j]
            _, spectral, pattern = decompose(window)
            rows.append(
                [spectral[8], pattern[0], pattern[1], np.log(max(np.diff(window).std(), 1e-8))]
            )
        output.append(rows)
    return np.asarray(output)


def forward(likelihood, initial, transition):
    result = np.zeros_like(likelihood)
    prior = np.broadcast_to(initial, (likelihood.shape[1], len(initial))).copy()
    for i, current in enumerate(likelihood):
        posterior = prior * current
        posterior /= posterior.sum(axis=1, keepdims=True)
        result[i] = posterior
        prior = posterior @ transition
    return result


def probabilities(bundle, x, mode):
    shape = x.shape[:2]
    model = bundle["mixture"]
    posterior = model.predict_proba(bundle["scaler"].transform(x.reshape(-1, x.shape[-1]))).reshape(
        *shape, 3
    )
    if mode == "emission":
        return posterior
    if mode == "constant":
        return np.broadcast_to(model.weights_, posterior.shape).copy()
    return forward(
        np.maximum(posterior / model.weights_, 1e-250), model.weights_, bundle["transition"]
    )


def utilities(opens, weights, i, j):
    held = np.zeros(3)
    wealth = np.ones(3)
    for t in range(i, i + 21):
        position = (weights[t, j] > 0).astype(float)
        wealth *= (
            1 + position * (opens[t + 2, j] / opens[t + 1, j] - 1) - abs(position - held) * 0.0008
        )
        held = position
    wealth *= 1 - held * 0.0008
    return np.r_[0.0, wealth - 1]
