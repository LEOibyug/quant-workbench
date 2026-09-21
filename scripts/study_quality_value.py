"""Fixed annual quality/valuation comparisons in original shared-cash engine."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quality_value_features import judge
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")
SEC = Path("artifacts/research/sec-quality")


def forecasts(frame, mode):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    syms = list(p.columns)
    r = np.diff(np.log(p.to_numpy()), axis=0)
    facts = {s: json.loads((SEC / f"{s}-facts.json").read_text()) for s in syms}
    verified = json.loads((ROOT / "2026-09-21-sec-50-issuers.json").read_text())
    out = {}
    examples = {}
    counts = dict(total=0, quality_available=0, value_available=0, selected=0)
    for i in range(63, len(p)):
        day = str(p.index[i])
        cov = LedoitWolf().fit(r[i - 63 : i]).covariance_ + np.eye(len(syms)) * 1e-12
        vol = np.sqrt(np.diag(cov))
        judgments = {
            s: judge(facts[s], day, s, float(p.iloc[i][s]), verified[s]["identity_verified"])
            for s in syms
        }
        eligible = [s for s in syms if judgments[s].get("candidate_pass")]
        available = [s for s in eligible if judgments[s]["earnings_yield"] is not None]
        if mode == "eligible_risk":
            selected = eligible
        elif mode == "quality":
            selected = sorted(eligible, key=lambda s: (-judgments[s]["quality"], s))[
                : int(np.ceil(len(eligible) / 2))
            ]
        else:
            qr = {
                s: i
                for i, s in enumerate(sorted(available, key=lambda s: (judgments[s]["quality"], s)))
            }
            vr = {
                s: i
                for i, s in enumerate(
                    sorted(available, key=lambda s: (judgments[s]["earnings_yield"], s))
                )
            }
            selected = sorted(available, key=lambda s: (-(qr[s] + vr[s]), s))[
                : int(np.ceil(len(available) / 2))
            ]
        raw = np.array([1 / vol[j] if s in selected else 0 for j, s in enumerate(syms)])
        w = np.minimum(0.2, 0.95 * raw / max(raw.sum(), 1e-12))
        w *= min(1, 0.1 / max(float(np.sqrt(w @ cov @ w * 252)), 1e-12))
        for s, weight in zip(syms, w, strict=True):
            out[(day, s)] = dict(target_weight=float(weight), volatility=0.01, status="ok")
        if day >= "2025-09-01":
            counts["total"] += len(syms)
            counts["quality_available"] += len(eligible)
            counts["value_available"] += len(available)
            counts["selected"] += len(selected)
            if not examples:
                examples = dict(date=day, judgments=judgments, selected=selected)
    return out, counts, examples


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        x["config"]
        for x in old["results"]
        if x["method"] == "fixed_ensemble" and x["cost_multiplier"] == 1
    )
    pools = {
        "original20": Repository().load_dataset(old["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    dest = ROOT / "2026-09-21-quality-value.json"
    for pool, frame in pools.items():
        for mode in ["quality", "quality_value", "eligible_risk"]:
            mapping, coverage, examples = forecasts(frame, mode)
            for mult in (1, 2):
                costs = dict(cfg["costs"])
                for k in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[k] *= mult
                config = PositionConfig(**{**cfg, "costs": costs})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    run = simulate_positions(
                        frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                    )
                row = dict(
                    pool=pool,
                    mode=mode,
                    cost_multiplier=mult,
                    metrics=run["metrics"],
                    coverage=coverage,
                    examples=examples,
                    contributions=run["contributions"],
                    config=run["config"],
                )
                results.append(row)
                dest.write_text(
                    json.dumps(
                        dict(status="running", results=results), ensure_ascii=False, indent=2
                    )
                )
                print(
                    pool,
                    mode,
                    mult,
                    round(run["metrics"]["return_pct"], 3),
                    round(run["metrics"]["max_drawdown_pct"], 3),
                    coverage,
                    flush=True,
                )
    dest.write_text(
        json.dumps(dict(status="completed", results=results), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
