"""Executed-account marginal utility labels, never ex-ante stock recommendations."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def exclude_targets(weights, excluded, cov, mode):
    w = weights.copy()
    w[excluded] = 0
    if mode == "cash":
        return w
    if mode != "redistribute":
        raise ValueError(mode)
    if w.sum() > 0:
        w = np.minimum(0.2, w * weights.sum() / w.sum())
        w *= min(1, 0.1 / max(np.sqrt(w @ cov @ w * 252), 1e-12))
    return w


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    config = PositionConfig(**cfg)
    source = Path("artifacts/models/conditional-policy-v2/history/daily.parquet")
    frame = pd.read_parquet(source)
    frame = frame[frame.day < "2025-09-01"]
    results = []
    labels = []
    destination = ROOT / "2026-09-21-marginal-capital.json"
    for start, end in [("2023-09-01", "2024-09-01"), ("2024-09-01", "2025-09-01")]:
        prior = sorted(frame.loc[frame.day < start, "day"].unique())[-273:]
        f = frame[(frame.day >= prior[0]) & (frame.day < end)]
        close = (
            f.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
        )
        if not np.isfinite(close.to_numpy()).all():
            raise ValueError("Incomplete panel")
        symbols = list(close.columns)
        base = rule_forecasts(f, config)
        returns = np.diff(np.log(close.to_numpy()), axis=0)
        prepared = []
        for i in range(63, len(close)):
            day = str(close.index[i])
            cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(len(symbols)) * 1e-12
            w = np.array([base.get((day, s), {}).get("target_weight", 0) for s in symbols])
            prepared.append((day, w, cov))

        def run(mapping, mode, excluded, f=f, start=start, end=end):
            with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                r = simulate_positions(f, config, start, end, daily_bars=True)
            results.append(
                dict(
                    start=start,
                    end_exclusive=end,
                    mode=mode,
                    excluded=excluded,
                    metrics=r["metrics"],
                    config=r["config"],
                    curve=r["curve"],
                    contributions=r["contributions"],
                )
            )
            save_results(destination, results)
            print(start, mode, excluded, round(r["metrics"]["return_pct"], 4), flush=True)
            return r

        baseline = run(base, "baseline", None)
        for mode in ("cash", "redistribute"):
            for j, symbol in enumerate(symbols):
                mapping = {}
                for day, w, cov in prepared:
                    target = exclude_targets(w, j, cov, mode)
                    for k, s in enumerate(symbols):
                        mapping[day, s] = {
                            **base.get((day, s), {}),
                            "target_weight": float(target[k]),
                            "status": "ok",
                        }
                r = run(mapping, mode, symbol)
                delta = baseline["metrics"]["return_pct"] - r["metrics"]["return_pct"]
                dd_delta = (
                    baseline["metrics"]["max_drawdown_pct"] - r["metrics"]["max_drawdown_pct"]
                )
                labels.append(
                    dict(
                        start=start,
                        label_available_after=end,
                        symbol=symbol,
                        mode=mode,
                        delta_return_pp=delta,
                        delta_utility_pp=delta - 0.5 * dd_delta,
                    )
                )
    save_results(destination, results, completed=True)
    (ROOT / "2026-09-21-marginal-capital-labels.json").write_text(json.dumps(labels, indent=2))


if __name__ == "__main__":
    main()
