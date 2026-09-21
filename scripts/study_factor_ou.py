"""Causal OU residual candidate and explicit factor hedge, research only."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import study_symmetric_trend as ledger
from quant_workbench.repository import Repository
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")


def residual_scores(history, factors=None):
    market = history.mean(axis=1) if factors is None else factors
    design = np.column_stack([np.ones(len(history)), market])
    coefficients = np.linalg.lstsq(design, history, rcond=None)[0]
    x = (history - design @ coefficients).cumsum(axis=0)
    means = np.full(history.shape[1], np.nan)
    equilibrium = np.full_like(means, np.nan)
    for j in range(history.shape[1]):
        fit = np.column_stack([np.ones(len(x) - 1), x[:-1, j]])
        a, b = np.linalg.lstsq(fit, x[1:, j], rcond=None)[0]
        if 0 < b < np.exp(-1 / 30):
            innovation = x[1:, j] - fit @ np.array([a, b])
            variance = np.var(innovation, ddof=2) / (1 - b * b)
            if variance > 1e-12:
                means[j] = a / (1 - b)
                equilibrium[j] = np.sqrt(variance)
    valid = np.isfinite(means)
    score = np.full_like(means, np.nan)
    if valid.any():
        score[valid] = (x[-1, valid] - (means[valid] - means[valid].mean())) / equilibrium[valid]
    return score, coefficients[1] if factors is None else coefficients[1:].T


def hedge(raw, beta, cov, mode):
    target = np.maximum(raw, 0) if mode == "long_only" else raw.copy()
    if mode == "beta_hedged":
        if abs(beta.sum()) < 1e-10:
            return np.zeros_like(raw)
        target -= float(target @ beta) / beta.sum()
    target *= min(1, 0.95 / max(abs(target).sum(), 1e-12), 0.2 / max(abs(target).max(), 1e-12))
    target *= min(1, 0.1 / max(np.sqrt(max(0, target @ cov @ target) * 252), 1e-12))
    return target


def forecasts(frame):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    r = np.diff(np.log(p.to_numpy()), axis=0)
    state = np.zeros(p.shape[1])
    output = {m: {} for m in ("long_only", "signed", "beta_hedged")}
    for i in range(60, len(p)):
        history = r[i - 60 : i]
        if not np.isfinite(history).all():
            raise ValueError("Incomplete history")
        score, beta = residual_scores(history)
        for j, s in enumerate(score):
            if not np.isfinite(s):
                state[j] = 0
            elif state[j] > 0:
                if s > -0.5:
                    state[j] = 0
            elif state[j] < 0:
                if s < 0.75:
                    state[j] = 0
            elif s < -1.25:
                state[j] = 1
            elif s > 1.25:
                state[j] = -1
        cov = LedoitWolf().fit(history).covariance_ + np.eye(p.shape[1]) * 1e-12
        inv = 1 / np.sqrt(np.diag(cov))
        raw = 0.95 * inv / inv.sum() * state
        for mode in output:
            target = hedge(raw, beta, cov, mode)
            output[mode][str(p.index[i])] = dict(zip(p.columns, target.tolist(), strict=True))
    return output


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    pools = {
        "original20": Repository().load_dataset(old["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    output = ROOT / "2026-09-21-factor-ou.json"
    for pool, frame in pools.items():
        for mode, mapping in forecasts(frame).items():
            for mult in (1, 2):
                with patch("study_symmetric_trend.forecasts", return_value=mapping):
                    result = ledger.simulate(frame, mode, mult, rebalance_days=1)
                result.update(pool=pool, candidate="factor_ou_v0", rebalance_days=1)
                results.append(result)
                output.write_text(json.dumps(dict(status="running", results=results), indent=2))
                print(
                    pool, mode, mult, result["return_pct"], result["max_drawdown_pct"], flush=True
                )
    output.write_text(json.dumps(dict(status="completed", results=results), indent=2))


if __name__ == "__main__":
    main()
