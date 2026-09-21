"""Frozen independent asset growth ranks and shared risk budget."""

import json
from pathlib import Path

import numpy as np
from asset_growth_features import judge
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")


def forecasts(
    frame,
    start="2025-09-01",
    end="2026-09-01",
    facts_root=Path("artifacts/research/sec-quality"),
    identities=None,
    excluded=(),
    judge_fn=judge,
    ratio_key="growth",
):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    syms = list(p.columns)
    returns = np.diff(np.log(p.to_numpy()), axis=0)
    facts = {s: json.loads((facts_root / f"{s}-facts.json").read_text()) for s in syms}
    verified = (
        identities
        if identities is not None
        else json.loads((ROOT / "2026-09-21-sec-50-issuers.json").read_text())
    )
    out = {m: {} for m in ("low_growth", "high_growth", "eligible")}
    diagnostics = []
    example = None
    evaluation_days = [str(d) for d in p.index if start <= str(d) < end]
    decisions = set(evaluation_days[::20])
    for i in range(63, len(p)):
        day = str(p.index[i])
        if day not in decisions:
            continue
        judgments = {
            s: judge_fn(facts[s], s, day, verified[s]["identity_verified"] and s not in excluded)
            for s in syms
        }
        eligible = sorted(s for s in syms if judgments[s].get("computable"))
        ordered = sorted(eligible, key=lambda s: (judgments[s][ratio_key], s))
        n = len(ordered) // 3
        low = ordered[:n]
        high = ordered[-n:] if n else []
        if n and judgments[low[-1]][ratio_key] >= judgments[high[0]][ratio_key]:
            n = 0
        sets = dict(low_growth=low, high_growth=high, eligible=eligible)
        if not n:
            sets = {k: [] for k in sets}
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(len(syms)) * 1e-12
        vol = np.sqrt(np.diag(cov))
        for mode, selected in sets.items():
            raw = np.array([1 / vol[j] if s in selected else 0 for j, s in enumerate(syms)])
            w = np.minimum(0.2, min(0.95, 0.2 * n) * raw / max(raw.sum(), 1e-12))
            w *= min(1, 0.1 / max(np.sqrt(w @ cov @ w * 252), 1e-12))
            for j, s in enumerate(syms):
                out[mode][day, s] = dict(
                    target_weight=float(w[j]), volatility=float(vol[j]), status="ok"
                )
        if day >= start:
            diagnostics.append(
                dict(
                    day=day,
                    eligible=eligible,
                    selected=sets,
                    budget=min(0.95, 0.2 * n),
                    judgments=judgments,
                )
            )
            if example is None:
                example = dict(day=day, judgments=judgments)
    return out, diagnostics, example
