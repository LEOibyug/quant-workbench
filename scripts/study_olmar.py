"""Constrained OLMAR with fixed published parameters and execution controls."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def project_capped(values, cap):
    if len(values) * cap < 1 - 1e-12:
        raise ValueError("Infeasible simplex")
    low, high = float(values.min() - cap), float(values.max())
    for _ in range(100):
        mid = (low + high) / 2
        if np.clip(values - mid, 0, cap).sum() > 1:
            low = mid
        else:
            high = mid
    return np.clip(values - (low + high) / 2, 0, cap)


def update(weights, relatives):
    centered = relatives - relatives.mean()
    denominator = float(centered @ centered)
    if denominator < 1e-12:
        return weights.copy()
    step = max(0, (10 - float(weights @ relatives)) / denominator)
    return project_capped(weights + step * centered, 0.2 / 0.95)


def forecasts(frame):
    prices = (
        frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    p = prices.to_numpy()
    if not np.isfinite(p).all() or (p <= 0).any():
        raise ValueError("Invalid or incomplete prices")
    r = np.diff(np.log(p), axis=0)
    b = np.full(len(prices.columns), 1 / len(prices.columns))
    maps = {"olmar": {}, "equal": {}}
    for i in range(4, len(p)):
        b = update(b, p[i - 4 : i + 1].mean(axis=0) / p[i])
        if i < 63:
            continue
        cov = LedoitWolf().fit(r[i - 63 : i]).covariance_ + np.eye(len(b)) * 1e-12
        for method in maps:
            w = 0.95 * (b.copy() if method == "olmar" else np.full(len(b), 1 / len(b)))
            w *= min(1, 0.1 / max(np.sqrt(w @ cov @ w * 252), 1e-12))
            for j, symbol in enumerate(prices.columns):
                maps[method][str(prices.index[i]), symbol] = dict(
                    target_weight=float(w[j]), volatility=float(np.sqrt(cov[j, j])), status="ok"
                )
    return maps


def main(output_name="2026-09-21-olmar.json"):
    original = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in original["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    pools = {
        "original20": Repository().load_dataset(original["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    out = ROOT / output_name
    for pool, frame in pools.items():
        for method, mapping in forecasts(frame).items():
            for frequency in (1, 5):
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
                    config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": frequency})
                    with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                        r = simulate_positions(
                            frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                        )
                    results.append(
                        dict(
                            pool=pool,
                            candidate=method,
                            rebalance_days=frequency,
                            cost_multiplier=mult,
                            config=r["config"],
                            metrics=r["metrics"],
                            contributions=r["contributions"],
                            curve=r["curve"],
                        )
                    )
                    save_results(out, results)
                    print(
                        pool,
                        method,
                        frequency,
                        mult,
                        r["metrics"]["return_pct"],
                        r["metrics"]["max_drawdown_pct"],
                        flush=True,
                    )
    save_results(out, results, completed=True)


if __name__ == "__main__":
    main()
