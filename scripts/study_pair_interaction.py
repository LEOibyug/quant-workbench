"""Predeclared pair exclusions through the shared-cash execution engine."""

import gzip
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")


def exclude_set(w, indices, cov, mode):
    out = w.copy()
    out[list(indices)] = 0
    if mode == "cash":
        return out
    if mode != "redistribute":
        raise ValueError(mode)
    if out.sum() > 0:
        out = np.minimum(0.2, out * w.sum() / out.sum())
        out *= min(1, 0.1 / max(np.sqrt(out @ cov @ out * 252), 1e-12))
    return out


def main():
    source = Path("artifacts/models/conditional-policy-v2/history/daily.parquet")
    frame = pd.read_parquet(source)
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        x["config"]
        for x in old["results"]
        if x["method"] == "fixed_ensemble" and x["cost_multiplier"] == 1
    )
    config = PositionConfig(**cfg)
    accounts, comparisons = [], []
    dest = ROOT / "2026-09-21-pair-interaction.json"
    for start, end in [("2023-09-01", "2024-09-01"), ("2024-09-01", "2025-09-01")]:
        prior = sorted(frame.loc[frame.day < start, "day"].unique())[-273:]
        f = frame[(frame.day >= prior[0]) & (frame.day < end)]
        close = (
            f.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
        )
        assert np.isfinite(close.to_numpy()).all() and (close.to_numpy() > 0).all()
        syms = list(close.columns)
        pairs = [syms[k : k + 2] for k in (0, 2, 4)]
        base = rule_forecasts(f, config)
        returns = np.diff(np.log(close.to_numpy()), axis=0)
        prepared = []
        for i in range(63, len(close)):
            day = str(close.index[i])
            cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(len(syms)) * 1e-12
            w = np.array([base[day, s]["target_weight"] for s in syms])
            prepared.append((day, cov, w))

        def run(excluded, mode):
            mapping = base
            if excluded:
                mapping = {}
                for day, cov, w in prepared:
                    target = exclude_set(w, [syms.index(s) for s in excluded], cov, mode)
                    for j, s in enumerate(syms):
                        mapping[day, s] = {**base[day, s], "target_weight": float(target[j])}
            with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                result = simulate_positions(f, config, start, end, daily_bars=True)
            assert all(p["positions"][s] == 0 for p in result["curve"] for s in excluded)
            assert all(t["symbol"] not in excluded for t in result["trades"])
            accounts.append(
                dict(start=start, end_exclusive=end, excluded=excluded, mode=mode, result=result)
            )
            print(start, mode, excluded, round(result["metrics"]["return_pct"], 4), flush=True)
            return result["metrics"]

        baseline = run([], "baseline")
        utility = lambda m: m["return_pct"] - 0.5 * m["max_drawdown_pct"]
        for mode in ["cash", "redistribute"]:
            singles = {s: run([s], mode) for s in syms[:6]}
            for pair in pairs:
                double = run(pair, mode)
                row = dict(start=start, end_exclusive=end, mode=mode, pair=pair)
                for name, measure in [("utility", utility), ("return", lambda m: m["return_pct"])]:
                    actual = measure(baseline) - measure(double)
                    additive = sum(measure(baseline) - measure(singles[s]) for s in pair)
                    row[name] = dict(
                        joint_delta_pp=actual,
                        sum_single_delta_pp=additive,
                        interaction_pp=actual - additive,
                        opposite_sign=bool(actual * additive < 0),
                    )
                comparisons.append(row)
        dest.write_text(json.dumps(dict(status="running", comparisons=comparisons), indent=2))
    archive = dest.with_suffix(".full.json.gz")
    archive.write_bytes(
        gzip.compress(json.dumps(accounts, separators=(",", ":")).encode(), mtime=0)
    )
    dest.write_text(
        json.dumps(
            dict(
                status="completed",
                validated=False,
                config=cfg,
                source=str(source),
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                full_archive=archive.name,
                accounts=len(accounts),
                comparisons=comparisons,
            ),
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
