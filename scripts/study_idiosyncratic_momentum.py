"""Frozen market-adjusted annual momentum, preserving alpha in adjusted returns."""

import json
import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def adjusted_score(history):
    market = history.mean(axis=1)
    design = np.column_stack([np.ones(len(history)), market])
    beta = np.linalg.lstsq(design, history, rcond=None)[0][1]
    adjusted = history - market[:, None] * beta[None, :]
    formation = adjusted[:-21]
    return formation.sum(axis=0) / np.maximum(
        formation.std(axis=0, ddof=1) * np.sqrt(len(formation)), 1e-8
    )


def forecasts(frame):
    prices = (
        frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    p = prices.to_numpy()
    if not np.isfinite(p).all() or (p <= 0).any():
        raise ValueError("Incomplete prices")
    logs = np.log(p)
    r = np.diff(logs, axis=0)
    maps = {name: {} for name in ("adjusted", "momentum12_1", "equal")}
    for i in range(252, len(p)):
        cov = LedoitWolf().fit(r[i - 63 : i]).covariance_ + np.eye(p.shape[1]) * 1e-12
        sigma = np.sqrt(np.diag(cov))
        scores = {
            "adjusted": adjusted_score(r[i - 252 : i]),
            "momentum12_1": logs[i - 21] - logs[i - 252],
        }
        for method in maps:
            if method == "equal":
                w = np.full(p.shape[1], 0.95 / p.shape[1])
            else:
                chosen = np.argsort(-scores[method], kind="stable")[: math.ceil(p.shape[1] / 4)]
                raw = np.zeros(p.shape[1])
                raw[chosen] = 1 / sigma[chosen]
                w = np.minimum(0.2, 0.95 * raw / raw.sum())
            w *= min(1, 0.1 / max(np.sqrt(w @ cov @ w * 252), 1e-12))
            for j, s in enumerate(prices.columns):
                maps[method][str(prices.index[i]), s] = dict(
                    target_weight=float(w[j]), volatility=float(sigma[j]), status="ok"
                )
    return maps


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    results = []
    output = ROOT / "2026-09-21-idiosyncratic-momentum.json"
    for pool, metadata in manifest.items():
        frame = pd.read_parquet(metadata["path"])
        for method, mapping in forecasts(frame).items():
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
                        candidate=method,
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
                    method,
                    mult,
                    r["metrics"]["return_pct"],
                    r["metrics"]["max_drawdown_pct"],
                    flush=True,
                )
    save_results(output, results, completed=True)


if __name__ == "__main__":
    main()
