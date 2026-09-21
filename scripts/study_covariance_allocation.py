"""Predeclared covariance-only shared-cash portfolios; no return forecasts."""

import gzip
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")


def save_results(path, results, completed=False):
    payload = dict(status="completed" if completed else "running", results=results)
    if completed:
        archive = path.with_suffix(".full.json.gz")
        archive.write_bytes(
            gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)
        )
    compact = []
    for row in results:
        curve = [
            {k: v for k, v in point.items() if k not in ("positions", "assets")}
            for point in row["curve"]
        ]
        compact.append({**row, "curve": curve})
    payload["results"] = compact
    if completed:
        payload["full_archive"] = archive.name
    path.write_text(json.dumps(payload, indent=2))


def allocate(cov, method):
    n = len(cov)
    budget = min(0.95, 0.2 * n)
    initial = np.full(n, budget / n)
    normalized = cov / np.mean(np.diag(cov))
    sigma = np.sqrt(np.diag(normalized))
    if method == "equal_risk_scaled":
        w = initial
        ok = True
    else:

        def objective(w):
            variance = float(w @ normalized @ w)
            return (
                variance
                if method == "minimum_variance"
                else -float(w @ sigma) / np.sqrt(max(variance, 1e-12))
            )

        result = minimize(
            objective,
            initial,
            method="SLSQP",
            bounds=[(0, 0.2)] * n,
            constraints=[{"type": "eq", "fun": lambda w: w.sum() - budget}],
            options={"ftol": 1e-10, "maxiter": 200},
        )
        ok = bool(
            result.success and np.isfinite(result.x).all() and abs(result.x.sum() - budget) < 1e-7
        )
        w = np.clip(result.x, 0, 0.2) if ok else np.zeros(n)
    w *= min(1, 0.10 / max(np.sqrt(w @ cov @ w * 252), 1e-12))
    return w, ok


def forecasts(frame):
    prices = (
        frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    logs = np.log(prices.to_numpy())
    returns = np.diff(logs, axis=0)
    maps = {m: {} for m in ("minimum_variance", "maximum_diversification", "equal_risk_scaled")}
    failures = dict.fromkeys(maps, 0)
    for i in range(63, len(prices)):
        history = returns[i - 63 : i]
        if not np.isfinite(history).all():
            raise ValueError("Incomplete prices")
        cov = LedoitWolf().fit(history).covariance_ + np.eye(prices.shape[1]) * 1e-12
        for method in maps:
            w, ok = allocate(cov, method)
            failures[method] += int(not ok)
            for j, symbol in enumerate(prices.columns):
                maps[method][str(prices.index[i]), symbol] = dict(
                    target_weight=float(w[j]),
                    volatility=float(np.sqrt(cov[j, j])),
                    status="ok" if ok else "optimizer_failed_cash",
                )
    return maps, failures


def main():
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
    out = ROOT / "2026-09-21-covariance-allocation.json"
    for pool, frame in pools.items():
        maps, failures = forecasts(frame)
        for method, mapping in maps.items():
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
                config = PositionConfig(**{**cfg, "costs": costs})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    r = simulate_positions(
                        frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                    )
                results.append(
                    dict(
                        pool=pool,
                        candidate=method,
                        cost_multiplier=mult,
                        optimizer_failures=failures[method],
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
                    mult,
                    r["metrics"]["return_pct"],
                    r["metrics"]["max_drawdown_pct"],
                    flush=True,
                )
    save_results(out, results, completed=True)


if __name__ == "__main__":
    main()
