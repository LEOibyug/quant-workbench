"""Frozen time-separated test of information continuity beyond price controls."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from information_continuity import path_metrics
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

ROOT = Path("docs/research-results")
FEATURES = ["pret", "pret_squared", "log_volatility63", "recent21", "continuity"]


def build_panel(frame, start, end):
    close = (
        frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    opening = frame.pivot(index="day", columns="symbol", values="open").reindex(
        index=close.index, columns=close.columns
    )
    assert np.isfinite(close.to_numpy()).all() and (close > 0).all().all()
    assert np.isfinite(opening.to_numpy()).all() and (opening > 0).all().all()
    logs = np.log(close.to_numpy())
    returns = np.diff(logs, axis=0)
    days = list(close.index)
    decisions = set([d for d in days if start <= d < end][::20])
    rows, coverage = [], []
    for i, day in enumerate(days):
        if day not in decisions:
            continue
        if i < 252 or i + 21 >= len(days) or days[i + 21] >= end:
            coverage.append(dict(day=day, accepted=False, reason="history_or_label_boundary"))
            continue
        pret, identity = path_metrics(returns[i - 252 : i - 21])
        eligible = pret > 0
        if eligible.sum() < 10:
            coverage.append(
                dict(
                    day=day,
                    accepted=False,
                    reason="fewer_than_10_winners",
                    count=int(eligible.sum()),
                )
            )
            continue
        vol = np.std(returns[i - 63 : i], axis=0, ddof=1)
        raw = np.column_stack(
            [pret, pret**2, np.log(np.maximum(vol, 1e-12)), logs[i] - logs[i - 21], -identity]
        )[eligible]
        sd = raw.std(axis=0)
        standardized = (raw - raw.mean(axis=0)) / np.where(sd > 1e-12, sd, 1)
        future = np.log(opening.iloc[i + 21].to_numpy() / opening.iloc[i + 1].to_numpy())[eligible]
        label = future - future.mean()
        for j, symbol in enumerate(close.columns[eligible]):
            rows.append(
                dict(
                    day=day,
                    symbol=symbol,
                    entry_day=days[i + 1],
                    exit_day=days[i + 21],
                    formation_start=days[i - 252],
                    formation_end=days[i - 21],
                    raw_features=dict(zip(FEATURES, raw[j].tolist(), strict=True)),
                    features=dict(zip(FEATURES, standardized[j].tolist(), strict=True)),
                    target=float(label[j]),
                    forward_log_return=float(future[j]),
                )
            )
        coverage.append(dict(day=day, accepted=True, count=int(eligible.sum())))
    return rows, coverage


def evaluate(rows, models):
    frame = pd.DataFrame(rows)
    x = np.array([[r["features"][k] for k in FEATURES] for r in rows])
    y = frame.target.to_numpy()
    pred = dict(
        base=models["base"].predict(x[:, :4]),
        augmented=models["augmented"].predict(x),
        zero=np.zeros(len(y)),
    )
    dates = []
    for day in sorted(frame.day.unique()):
        mask = (frame.day == day).to_numpy()
        record = dict(day=day, n=int(mask.sum()))
        for name, p in pred.items():
            record[name] = dict(
                mse=float(np.mean((p[mask] - y[mask]) ** 2)),
                spearman=float(spearmanr(p[mask], y[mask]).statistic)
                if np.std(p[mask]) > 0 and np.std(y[mask]) > 0
                else None,
            )
        dates.append(record)
    delta = np.array([d["augmented"]["mse"] - d["base"]["mse"] for d in dates])
    rng = np.random.default_rng(922)
    n = len(delta)
    if n < 3:
        raise ValueError("Too few date groups for the frozen diagnostic")
    samples = []
    for _ in range(2000):
        starts = rng.integers(0, n, size=(n + 2) // 3)
        indices = np.concatenate([(a + np.arange(3)) % n for a in starts])[:n]
        samples.append(float(delta[indices].mean()))
    return dict(
        rows=len(rows),
        dates=dates,
        average_mse={m: float(np.mean([d[m]["mse"] for d in dates])) for m in pred},
        average_spearman={
            m: float(np.mean([d[m]["spearman"] for d in dates if d[m]["spearman"] is not None]))
            for m in ["base", "augmented"]
        },
        augmented_minus_base_mse=float(delta.mean()),
        descriptive_block_interval=np.quantile(samples, [0.025, 0.975]).tolist(),
    )


def main():
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    old_paths = [
        "artifacts/research/annual-momentum/random10-temporal.parquet",
        "artifacts/research/transfer12-temporal-2026-09-21/combined.parquet",
    ]
    new_paths = [v["path"] for v in manifest.values()] + [
        "artifacts/research/transfer12-2026-09-21/daily.parquet"
    ]

    def read(paths):
        frames = [pd.read_parquet(p) for p in paths]
        common = set.intersection(*(set(f.day) for f in frames))
        frame = pd.concat([f[f.day.isin(common)] for f in frames], ignore_index=True)
        assert not frame.duplicated(["day", "symbol"]).any()
        return frame

    old = read(old_paths)
    recent = read(new_paths)
    past, past_coverage = build_panel(old, "2022-09-01", "2025-09-01")
    latest, latest_coverage = build_panel(recent, "2025-09-01", "2026-09-01")
    train = [r for r in past if r["day"] < "2024-09-01" and r["exit_day"] < "2024-09-01"]
    validation = [r for r in past if r["day"] >= "2024-09-01"]
    assert max(r["exit_day"] for r in train) < min(r["day"] for r in validation)
    # Truncating unavailable future rows must preserve all already-matured observations.
    prefix, _ = build_panel(old[old.day < "2024-09-01"], "2022-09-01", "2024-09-01")
    assert prefix == train
    x = np.array([[r["features"][k] for k in FEATURES] for r in train])
    y = np.array([r["target"] for r in train])
    sizes = pd.Series([r["day"] for r in train]).value_counts()
    weights = np.array([1 / sizes[r["day"]] for r in train])
    models = {
        m: Ridge(alpha=10, fit_intercept=False).fit(x[:, :n], y, sample_weight=weights)
        for m, n in [("base", 4), ("augmented", 5)]
    }
    output = dict(
        status="completed",
        source_hashes={
            p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in old_paths + new_paths
        },
        train_rows=len(train),
        train_dates=len(sizes),
        train_last_label=max(r["exit_day"] for r in train),
        coefficients={
            m: dict(zip(FEATURES, model.coef_.tolist(), strict=False))
            for m, model in models.items()
        },
        evaluations=dict(
            temporal22=evaluate(validation, models), latest62=evaluate(latest, models)
        ),
        checks=dict(prefix_invariance=True, strict_label_boundary=True, unique_symbol_days=True),
        coverage=dict(past=past_coverage, latest=latest_coverage),
    )
    (ROOT / "2026-09-22-fip-conditional.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    )
    (ROOT / "2026-09-22-fip-conditional-panel.json").write_text(
        json.dumps(dict(past=past, latest=latest), indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in output.items() if k not in ["source_hashes", "coverage"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
