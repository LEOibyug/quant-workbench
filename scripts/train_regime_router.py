"""Fit descriptive regimes and utility binding before the frozen cutoff."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from learned_applicability import CLASSES, prepare
from regime_router import features, probabilities, utilities
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler


def main():
    source = Path("artifacts/models/conditional-policy-v2/history/daily.parquet")
    frame = pd.read_parquet(source)
    frame = frame[frame.day.astype(str) < "2025-09-01"]
    close, opens, weights = prepare(frame)
    x = features(np.log(close.to_numpy()))
    training = np.asarray(close.index[63:].astype(str) < "2024-09-01")
    flat = x[training].reshape(-1, x.shape[-1])
    scaler = StandardScaler().fit(flat)
    mixture = GaussianMixture(
        n_components=3,
        covariance_type="full",
        n_init=3,
        max_iter=200,
        reg_covar=1e-4,
        random_state=20250901,
    ).fit(scaler.transform(flat))
    labels = mixture.predict(scaler.transform(flat)).reshape(training.sum(), len(close.columns))
    counts = np.full((3, 3), 1 / 3)
    np.add.at(counts, (labels[:-1].ravel(), labels[1:].ravel()), 1)
    transition = counts / counts.sum(axis=1, keepdims=True)
    bundle = dict(scaler=scaler, mixture=mixture, transition=transition)
    posterior = probabilities(bundle, x, "markov")
    reward = np.zeros((3, 4))
    mass = np.zeros(3)
    label_dates = []
    for i in range(63, len(close) - 22, 21):
        if str(close.index[i + 22]) >= "2024-09-01":
            continue
        label_dates.append(str(close.index[i + 22]))
        for j in range(len(close.columns)):
            p = posterior[i - 63, j]
            reward += p[:, None] * utilities(opens, weights, i, j)
            mass += p
    reward /= mass[:, None]
    binding = reward.argmax(axis=1)
    bundle.update(binding=binding, utility=reward, trained_before="2024-09-01")
    root = Path("artifacts/models/regime-router-v0")
    root.mkdir(parents=True, exist_ok=True)
    path = root / "model.joblib"
    joblib.dump(bundle, path)
    validation = x[~training].reshape(-1, x.shape[-1])
    report = dict(
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        history_start=str(close.index[0]),
        last_training_feature=str(close.index[63:][training][-1]),
        last_training_label=max(label_dates),
        training_windows=int(training.sum() * len(close.columns)),
        utility_windows=len(label_dates) * len(close.columns),
        validation_windows=len(validation),
        converged=bool(mixture.converged_),
        transition=transition.tolist(),
        initial=mixture.weights_.tolist(),
        centroids=scaler.inverse_transform(mixture.means_).tolist(),
        state_utility=reward.tolist(),
        state_binding=[CLASSES[k] for k in binding],
        binding_collapsed=len(set(binding.tolist())) == 1,
        validation_log_density=float(mixture.score(scaler.transform(validation))),
    )
    Path("docs/research-results/2026-09-21-regime-router-training.json").write_text(
        json.dumps(report, indent=2)
    )
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
