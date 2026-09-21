"""Frozen financial feature ablation for executed-account marginal utility labels."""

import hashlib
import json
from datetime import date
from pathlib import Path

import joblib
import numpy as np
from build_quality_snapshots import annual_values
from quality_value_features import EXCLUDED
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path("docs/research-results")


def financial(facts, symbol, cutoff):
    result = dict(features=[None] * 5, reason="会计范围或发行人未核验", sources={})
    if symbol in EXCLUDED or symbol == "XOM":
        return result
    series = {
        k: {r["end"]: r for r in annual_values(facts, k, cutoff)}
        for k in ("net_income", "operating_cash_flow", "revenue", "assets")
    }
    common = sorted(set.intersection(*(set(r) for r in series.values())), reverse=True)
    if not common:
        return dict(result, reason="没有共同年度")
    end = common[0]
    prior = next(
        (
            e
            for e in sorted(set(series["assets"]) & set(series["revenue"]), reverse=True)
            if 330 <= (date.fromisoformat(end) - date.fromisoformat(e)).days <= 400
        ),
        None,
    )
    if prior is None or (date.fromisoformat(cutoff) - date.fromisoformat(end)).days > 550:
        return dict(result, reason="缺少可比前期或财务陈旧")
    sources = {k: s[end] for k, s in series.items()}
    sources.update(prior_assets=series["assets"][prior], prior_revenue=series["revenue"][prior])
    if (
        len({sources[k]["accn"] for k in series}) != 1
        or len({sources[k].get("start") for k in ("net_income", "operating_cash_flow", "revenue")})
        != 1
    ):
        return dict(result, reason="当期财务不同申报或区间", sources=sources)
    ni, cf, rev, a, a0, r0 = [
        sources[k]["val"]
        for k in (
            "net_income",
            "operating_cash_flow",
            "revenue",
            "assets",
            "prior_assets",
            "prior_revenue",
        )
    ]
    if min(a, a0, r0) <= 0:
        return dict(result, reason="非正分母", sources=sources)
    average = (a + a0) / 2
    return dict(
        features=[ni / average, cf / average, (ni - cf) / average, rev / r0 - 1, a / a0 - 1],
        reason="可计算代理，未经适用性确认",
        sources=sources,
    )


def encode(x, medians):
    missing = ~np.isfinite(x)
    return np.c_[np.where(missing, medians, x), missing.astype(float)]


def main():
    label_path = ROOT / "2026-09-21-marginal-model-labels.json"
    data = json.loads(label_path.read_text())
    assert data["status"] == "completed"
    symbols = {r["symbol"] for g in data["groups"] for r in g["rows"]}
    cache = {s: Path(f"artifacts/research/sec-quality/{s}-facts.json") for s in symbols}
    facts = {s: json.loads(p.read_text()) for s, p in cache.items()}
    rows = []
    for group in data["groups"]:
        for r in group["rows"]:
            f = financial(facts[r["symbol"]], r["symbol"], group["signal_date"])
            assert all(v["filed"] < group["signal_date"] for v in f["sources"].values())
            rows.append(
                dict(
                    symbol=r["symbol"],
                    date=group["signal_date"],
                    split=group["split"],
                    label=r["utility"],
                    price=r["features"],
                    financial=f,
                )
            )
    destination = ROOT / "2026-09-21-financial-marginal.json"
    report = dict(
        label_sha256=hashlib.sha256(label_path.read_bytes()).hexdigest(),
        facts_sha256={s: hashlib.sha256(p.read_bytes()).hexdigest() for s, p in cache.items()},
        rows=rows,
        models={},
    )
    train = np.array([r["split"] == "train" for r in rows])
    y = np.array([r["label"] for r in rows])
    px = np.array([r["price"] for r in rows])
    fx = np.array([r["financial"]["features"] for r in rows], dtype=float)
    report["coverage"] = {
        s: dict(
            windows=int(sum(np.array([r["split"] == s for r in rows]))),
            complete=int(
                sum(np.isfinite(fx).all(axis=1) & np.array([r["split"] == s for r in rows]))
            ),
        )
        for s in ("train", "validation")
    }
    report["constant_mse"] = float(np.mean((y[~train] - y[train].mean()) ** 2))
    for name, x in [("price", px), ("financial", fx), ("combined", np.c_[px, fx])]:
        medians = np.array(
            [np.median(c[np.isfinite(c)]) if np.isfinite(c).any() else 0 for c in x[train].T]
        )
        z = encode(x, medians)
        model = make_pipeline(StandardScaler(), Ridge(alpha=10)).fit(z[train], y[train])
        pred = model.predict(z[~train])
        actual = y[~train]
        selected = pred > 0
        artifact = Path(f"artifacts/models/financial-marginal-v0/{name}.joblib")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(dict(model=model, medians=medians), artifact)
        report["models"][name] = dict(
            sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            mse=float(np.mean((pred - actual) ** 2)),
            correlation=float(np.corrcoef(pred, actual)[0, 1]),
            positive_fraction=float(selected.mean()),
            positive_actual_mean=float(actual[selected].mean()) if selected.any() else None,
            nonpositive_actual_mean=float(actual[~selected].mean()) if (~selected).any() else None,
            predictions=pred.tolist(),
        )
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    print(
        json.dumps(
            dict(
                coverage=report["coverage"],
                constant_mse=report["constant_mse"],
                models={
                    k: {a: b for a, b in v.items() if a != "predictions"}
                    for k, v in report["models"].items()
                },
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
