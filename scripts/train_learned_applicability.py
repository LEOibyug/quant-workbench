"""Train predeclared classifiers without using evaluation-period prices."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from learned_applicability import CLASSES, feature, prepare, utility_label
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def main():
    source = Path("artifacts/models/conditional-policy-v2/history/daily.parquet")
    frame = pd.read_parquet(source)
    frame = frame[frame.day.astype(str) < "2025-09-01"]
    close, opens, weights = prepare(frame)
    logs = np.log(close.to_numpy())
    data = {"train": [], "validation": []}
    for i in range(63, len(close) - 22, 5):
        end = str(close.index[i + 22])
        split = (
            "train"
            if end < "2024-09-01"
            else (
                "validation"
                if str(close.index[i - 63]) >= "2024-09-01" and end < "2025-09-01"
                else None
            )
        )
        if split:
            for j in range(len(close.columns)):
                data[split].append(
                    (
                        feature(logs, weights, i, j),
                        utility_label(opens, weights, i, j),
                        str(close.index[i - 63]),
                        str(close.index[i]),
                        end,
                    )
                )
    arrays = {
        s: (np.array([r[0] for r in rows]), np.array([r[1] for r in rows]))
        for s, rows in data.items()
    }
    models = {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=1000)),
        "hist_gradient": HistGradientBoostingClassifier(
            max_iter=100,
            max_leaf_nodes=7,
            min_samples_leaf=50,
            l2_regularization=10,
            learning_rate=0.05,
            random_state=20250901,
        ),
    }
    root = Path("artifacts/models/learned-applicability-v0")
    root.mkdir(parents=True, exist_ok=True)
    report = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "classes": CLASSES,
        "history_start": str(close.index[0]),
        "history_end": str(close.index[-1]),
        "splits": {},
        "models": {},
    }
    for split, rows in data.items():
        report["splits"][split] = {
            "rows": len(rows),
            "class_counts": np.bincount(arrays[split][1], minlength=4).tolist(),
            "first_window_start": min(r[2] for r in rows),
            "last_signal": max(r[3] for r in rows),
            "last_label_end": max(r[4] for r in rows),
        }
    x, y = arrays["validation"]
    majority = np.bincount(arrays["train"][1]).argmax()
    report["majority_baseline"] = {
        "class": int(majority),
        "accuracy": accuracy_score(y, np.full(len(y), majority)),
        "balanced_accuracy": balanced_accuracy_score(y, np.full(len(y), majority)),
    }
    for name, model in models.items():
        model.fit(*arrays["train"])
        pred = model.predict(x)
        path = root / f"{name}.joblib"
        joblib.dump(model, path)
        report["models"][name] = {
            "accuracy": accuracy_score(y, pred),
            "balanced_accuracy": balanced_accuracy_score(y, pred),
            "log_loss": log_loss(y, model.predict_proba(x), labels=model.classes_),
            "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    report["selected"] = max(
        report["models"], key=lambda n: report["models"][n]["balanced_accuracy"]
    )
    Path("docs/research-results/2026-09-21-learned-applicability-training.json").write_text(
        json.dumps(report, indent=2)
    )
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
