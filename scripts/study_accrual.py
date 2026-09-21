"""Frozen low/high accrual comparison with equal eligibility and shared cash."""

import json
import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from accrual_features import judge
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def forecasts(frame):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    syms = list(p.columns)
    returns = np.diff(np.log(p.to_numpy()), axis=0)
    facts = {
        s: json.loads(Path(f"artifacts/research/sec-quality/{s}-facts.json").read_text())
        for s in syms
    }
    verified = json.loads((ROOT / "2026-09-21-sec-50-issuers.json").read_text())
    out = {m: {} for m in ("low", "high", "eligible")}
    diagnostics = []
    example = None
    for i in range(63, len(p)):
        day = str(p.index[i])
        judgments = {s: judge(facts[s], day, s, verified[s]["identity_verified"]) for s in syms}
        eligible = sorted(
            [s for s in syms if judgments[s].get("candidate_eligible")],
            key=lambda s: (judgments[s]["score"], s),
        )
        n = math.ceil(len(eligible) / 3)
        sets = (
            {"low": eligible[:n], "high": list(reversed(eligible))[:n], "eligible": eligible}
            if len(eligible) >= 3
            else dict(low=[], high=[], eligible=[])
        )
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
        if day >= "2025-09-01":
            diagnostics.append(dict(day=day, eligible=eligible, selected=sets))
            if example is None:
                example = dict(day=day, judgments=judgments)
    return out, diagnostics, example


def main():
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    results = []
    diagnostics = {}
    output = ROOT / "2026-09-21-accrual.json"
    for pool, meta in manifest.items():
        frame = pd.read_parquet(meta["path"])
        maps, coverage, example = forecasts(frame)
        diagnostics[pool] = dict(coverage=coverage, example=example)
        for mode, mapping in maps.items():
            for mult in (1, 2):
                costs = dict(cfg["costs"])
                for key in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[key] *= mult
                config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": 20})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    r = simulate_positions(
                        frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                    )
                results.append(
                    dict(
                        pool=pool,
                        candidate=mode,
                        cost_multiplier=mult,
                        config=r["config"],
                        metrics=r["metrics"],
                        contributions=r["contributions"],
                        curve=r["curve"],
                    )
                )
                save_results(output, results)
                print(
                    pool,
                    mode,
                    mult,
                    r["metrics"]["return_pct"],
                    r["metrics"]["max_drawdown_pct"],
                    flush=True,
                )
        (ROOT / "2026-09-21-accrual-coverage.json").write_text(
            json.dumps(diagnostics, indent=2, ensure_ascii=False)
        )
    save_results(output, results, completed=True)


if __name__ == "__main__":
    main()
