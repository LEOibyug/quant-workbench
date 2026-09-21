"""Frozen low-beta stock selection with shared risk budget and high-beta control."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def forecasts(frame):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    values = p.to_numpy()
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Invalid prices")
    logs = np.log(values)
    returns = np.diff(logs, axis=0)
    maps = {m: {} for m in ("equal", "low_beta", "high_beta")}
    for i in range(252, len(p)):
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(p.shape[1]) * 1e-12
        sigma = np.sqrt(np.diag(cov))
        history = returns[i - 252 : i]
        market = history.mean(axis=1)
        centered = history - history.mean(axis=0)
        m = market - market.mean()
        denominator = m @ m
        if denominator <= 1e-15:
            raise ValueError("Degenerate market proxy")
        beta = centered.T @ m / denominator
        order = np.argsort(beta, kind="stable")
        low, high = np.zeros(p.shape[1]), np.zeros(p.shape[1])
        n = p.shape[1] // 2
        low[order[:n]] = min(0.2, 0.95 / n)
        high[order[-n:]] = min(0.2, 0.95 / n)
        for mode, raw in [
            ("equal", np.minimum(0.2, np.full(p.shape[1], 0.95 / p.shape[1]))),
            ("low_beta", low),
            ("high_beta", high),
        ]:
            target = raw * min(1, 0.1 / max(np.sqrt(raw @ cov @ raw * 252), 1e-12))
            for j, symbol in enumerate(p.columns):
                maps[mode][str(p.index[i]), symbol] = dict(
                    target_weight=float(target[j]), volatility=float(sigma[j]), status="ok"
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
    windows = [(pool, meta["path"], "2025-09-01", "2026-09-01") for pool, meta in manifest.items()]
    for start, end in [
        ("2022-09-01", "2023-09-01"),
        ("2023-09-01", "2024-09-01"),
        ("2024-09-01", "2025-09-01"),
        ("2022-09-01", "2025-09-01"),
    ]:
        windows.append(
            (
                "random10_temporal",
                "artifacts/research/annual-momentum/random10-temporal.parquet",
                start,
                end,
            )
        )
    rows = []
    dest = ROOT / "2026-09-21-low-beta.json"
    for pool, path, start, end in windows:
        f = pd.read_parquet(path)
        prior = sorted(f.loc[f.day < start, "day"].unique())[-273:]
        frame = f[(f.day >= prior[0]) & (f.day < end)]
        maps = forecasts(frame)
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

            def record(method, r, pool=pool, start=start, end=end, mult=mult):
                rows.append(
                    dict(
                        pool=pool,
                        start=start,
                        end_exclusive=end,
                        method=method,
                        cost_multiplier=mult,
                        config=r["config"],
                        metrics=r["metrics"],
                        curve=r["curve"],
                        contributions=r["contributions"],
                    )
                )
                save_results(dest, rows)
                print(
                    pool,
                    start,
                    method,
                    mult,
                    round(r["metrics"]["return_pct"], 4),
                    round(r["metrics"]["max_drawdown_pct"], 4),
                    flush=True,
                )

            for method, mapping in maps.items():
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    result = simulate_positions(frame, config, start, end, daily_bars=True)
                record(method, result)
    save_results(dest, rows, completed=True)


if __name__ == "__main__":
    main()
