"""Audit label persistence and counterfactual dependence without fitting a selector."""

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ROOT = Path("docs/research-results")


def predict(groups, current):
    train = [r for g in groups if g["split"] == "train" for r in g["rows"]]
    assert all(g["label_end"] < current["signal_date"] for g in groups if g["split"] == "train")
    mean = float(np.mean([r["utility"] for r in train]))
    past = [
        g
        for g in groups
        if g["label_end"] <= current["signal_date"] and g["signal_date"] < current["signal_date"]
    ]
    last = max(past, key=lambda g: g["label_end"])
    by_symbol = {r["symbol"]: r["utility"] for r in last["rows"]}
    return {
        "pooled_mean": [mean for _ in current["rows"]],
        "stock_mean": [
            float(np.mean([p["utility"] for p in train if p["symbol"] == r["symbol"]]))
            for r in current["rows"]
        ],
        "last_matured": [by_symbol[r["symbol"]] for r in current["rows"]],
    }, last["label_end"]


def stats(actual, predicted):
    y, p = np.asarray(actual), np.asarray(predicted)
    return dict(
        mse=float(np.mean((y - p) ** 2)),
        rank_correlation=float(spearmanr(y, p).statistic)
        if np.ptp(p) > 0 and np.ptp(y) > 0
        else None,
        positive_count=int((p > 0).sum()),
        zero_count=int((p == 0).sum()),
        positive_actual_mean=float(y[p > 0].mean()) if (p > 0).any() else None,
        nonpositive_actual_mean=float(y[p <= 0].mean()) if (p <= 0).any() else None,
    )


def main():
    monthly_path = ROOT / "2026-09-21-marginal-model-labels.json"
    annual_path = ROOT / "2026-09-21-marginal-capital-labels.json"
    groups = json.loads(monthly_path.read_text())["groups"]
    output = []
    for g in sorted(groups, key=lambda g: g["signal_date"]):
        if g["split"] != "validation":
            continue
        predictions, end = predict(groups, g)
        actual = [r["utility"] for r in g["rows"]]
        for mode, p in predictions.items():
            output.append(
                dict(
                    date=g["signal_date"],
                    label_end=g["label_end"],
                    mode=mode,
                    latest_matured_end=end,
                    symbols=[r["symbol"] for r in g["rows"]],
                    predictions=p,
                    actual=actual,
                    **stats(actual, p),
                )
            )
    summary = {}
    for mode in ("pooled_mean", "stock_mean", "last_matured"):
        rows = [r for r in output if r["mode"] == mode]
        summary[mode] = stats(
            [x for r in rows for x in r["actual"]], [x for r in rows for x in r["predictions"]]
        )
    annual = json.loads(annual_path.read_text())
    lookup = {(r["start"], r["symbol"], r["mode"]): r["delta_utility_pp"] for r in annual}
    paired = []
    for start, symbol, mode in sorted(lookup):
        if mode != "cash":
            continue
        a, b = lookup[start, symbol, "cash"], lookup[start, symbol, "redistribute"]
        paired.append(
            dict(
                start=start,
                symbol=symbol,
                cash=a,
                redistribute=b,
                opposite_sign=bool(a * b < 0),
                either_zero=bool(a == 0 or b == 0),
            )
        )
    years = sorted({r["start"] for r in annual})
    persistence = []
    for mode in ("cash", "redistribute"):
        syms = sorted({r["symbol"] for r in annual})
        a = [lookup[years[0], s, mode] for s in syms]
        b = [lookup[years[1], s, mode] for s in syms]
        persistence.append(
            dict(
                mode=mode,
                **stats(b, a),
                opposite_sign_count=int((np.array(a) * np.array(b) < 0).sum()),
                stocks=len(syms),
            )
        )
    report = dict(
        status="completed",
        validated=False,
        provenance={
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (monthly_path, annual_path)
        },
        monthly_summary=summary,
        monthly_rows=output,
        annual_intervention_pairs=paired,
        annual_opposite_sign_count=sum(r["opposite_sign"] for r in paired),
        annual_pair_count=len(paired),
        annual_persistence=persistence,
    )
    (ROOT / "2026-09-21-marginal-stability.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in ("monthly_rows", "annual_intervention_pairs", "provenance")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
