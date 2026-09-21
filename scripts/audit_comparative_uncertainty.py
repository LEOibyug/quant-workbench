"""Paired block-bootstrap diagnostics for an explicit, limited comparison family."""

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path("docs/research-results")
SPECS = [
    ("tsmom", "equal", ["inverse_vol", "tsmom"]),
    ("low-beta", "equal", ["low_beta", "high_beta"]),
    ("event-reaction", "all", ["positive", "negative"]),
    ("volume-event", "inverse_vol", ["high", "low"]),
    ("online-mixture", "static_mix", ["wealth_mix"]),
]


def draw_indices(n, rng, block=21):
    starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
    return np.concatenate([np.arange(s, s + block) for s in starts])[:n]


def account_returns(row):
    equity = np.array([p["equity"] for p in row["curve"]], dtype=float)
    initial = row["config"]["costs"]["initial_cash"]
    return equity / np.r_[initial, equity[:-1]] - 1


def main():
    metadata = {}
    columns = []
    labels = []
    calendar = None
    for study, baseline, methods in SPECS:
        path = ROOT / f"2026-09-21-{study}.json"
        metadata[study] = hashlib.sha256(path.read_bytes()).hexdigest()
        data = json.loads(path.read_text())
        assert data["status"] == "completed"
        records = data["results"]
        for method in methods:
            for cost in (1, 2):
                for pool in ("original20", "alternate20", "random10"):

                    def find(m, records=records, pool=pool, cost=cost):
                        found = [
                            r
                            for r in records
                            if r["method"] == m
                            and r["pool"] == pool
                            and r["cost_multiplier"] == cost
                            and r["start"] == "2025-09-01"
                            and r["end_exclusive"] == "2026-09-01"
                        ]
                        assert len(found) == 1
                        return found[0]

                    a, b = find(method), find(baseline)
                    dates = [p["date"] for p in a["curve"]]
                    assert dates == [p["date"] for p in b["curve"]]
                    if calendar is None:
                        calendar = dates
                    assert dates == calendar
                    columns.append(account_returns(a) - account_returns(b))
                    labels.append(
                        dict(
                            study=study,
                            method=method,
                            baseline=baseline,
                            cost=cost,
                            pool=pool,
                            terminal_return_difference_pp=a["metrics"]["return_pct"]
                            - b["metrics"]["return_pct"],
                        )
                    )
    x = np.array(columns).T
    n = len(x)
    mean = x.mean(axis=0)
    rng = np.random.default_rng(20250921)
    boot = np.array([x[draw_indices(n, rng)].mean(axis=0) for _ in range(1000)])
    se = boot.std(axis=0, ddof=1)
    if (se <= 1e-15).any():
        raise ValueError("Degenerate comparison")
    null_max = ((boot - mean) / se).max(axis=1)
    for j, label in enumerate(labels):
        label.update(
            annualized_arithmetic_difference_pp=float(mean[j] * 25200),
            percentile_95_pp=(np.quantile(boot[:, j], [0.025, 0.975]) * 25200).tolist(),
            adjusted_one_sided_p=float((1 + sum(null_max >= mean[j] / se[j])) / 1001),
        )
    cross = []
    for i in range(0, len(labels), 3):
        group = labels[i : i + 3]
        assert len({g["pool"] for g in group}) == 3
        minimum = boot[:, i : i + 3].min(axis=1) * 25200
        cross.append(
            dict(
                study=group[0]["study"],
                method=group[0]["method"],
                cost=group[0]["cost"],
                minimum_observed_annualized_pp=float(mean[i : i + 3].min() * 25200),
                minimum_unadjusted_percentile_95_pp=np.quantile(minimum, [0.025, 0.975]).tolist(),
            )
        )
    report = dict(
        source_sha256=metadata,
        dates=calendar,
        block=21,
        replicates=1000,
        seed=20250921,
        comparisons=labels,
        cross_pool=cross,
        note="开发诊断；仅54对比校正，不涵盖全部研究选择；非独立确认",
    )
    (ROOT / "2026-09-21-comparative-uncertainty.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(
        "Comparisons",
        len(labels),
        "dates",
        n,
        "adjusted p<.05",
        sum(r["adjusted_one_sided_p"] < 0.05 for r in labels),
    )
    for r in cross:
        print(r)


if __name__ == "__main__":
    main()
