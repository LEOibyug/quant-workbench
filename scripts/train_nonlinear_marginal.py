"""One frozen nonlinear capacity ablation; no tuning or deployment."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesRegressor
from train_financial_marginal import encode

ROOT = Path("docs/research-results")


def main():
    path = ROOT / "2026-09-21-financial-marginal.json"
    data = json.loads(path.read_text())
    rows = data["rows"]
    train = np.array([r["split"] == "train" for r in rows])
    y = np.array([r["label"] for r in rows])
    px = np.array([r["price"] for r in rows])
    fx = np.array([r["financial"]["features"] for r in rows], dtype=float)
    validation = [r for r in rows if r["split"] == "validation"]
    report = dict(
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        constant_mse=data["constant_mse"],
        models={},
    )
    for name, x in [("price", px), ("financial", fx), ("combined", np.c_[px, fx])]:
        medians = np.array(
            [np.median(c[np.isfinite(c)]) if np.isfinite(c).any() else 0 for c in x[train].T]
        )
        z = encode(x, medians)
        model = ExtraTreesRegressor(
            n_estimators=300,
            max_depth=3,
            min_samples_leaf=40,
            max_features=1.0,
            bootstrap=False,
            random_state=20250921,
            n_jobs=1,
        )
        model.fit(z[train], y[train])
        pred = model.predict(z[~train])
        actual = y[~train]
        selected = pred > 0
        groups = []
        for day in sorted({r["date"] for r in validation}):
            mask = np.array([r["date"] == day for r in validation])
            a = actual[mask]
            p = pred[mask] > 0
            groups.append(
                dict(
                    date=day,
                    positive_count=int(p.sum()),
                    positive_actual=float(a[p].mean()) if p.any() else None,
                    nonpositive_actual=float(a[~p].mean()) if (~p).any() else None,
                )
            )
        artifact = Path(f"artifacts/models/nonlinear-marginal-v0/{name}.joblib")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(dict(model=model, medians=medians), artifact)
        report["models"][name] = dict(
            artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            mse=float(np.mean((pred - actual) ** 2)),
            ridge_mse=data["models"][name]["mse"],
            correlation=float(np.corrcoef(pred, actual)[0, 1]),
            positive_fraction=float(selected.mean()),
            positive_actual=float(actual[selected].mean()) if selected.any() else None,
            nonpositive_actual=float(actual[~selected].mean()) if (~selected).any() else None,
            groups=groups,
            predictions=pred.tolist(),
            params=model.get_params(),
        )
    (ROOT / "2026-09-21-nonlinear-marginal.json").write_text(
        json.dumps(report, indent=2, allow_nan=False)
    )
    print(
        json.dumps(
            {
                k: {a: b for a, b in v.items() if a not in ("params", "predictions", "groups")}
                for k, v in report["models"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
