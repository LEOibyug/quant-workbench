"""Frozen literature-inspired 12-1 momentum with portfolio volatility control.

The candidate is registered before evaluation: rank stocks by the return from
252 to 21 sessions ago, take the top quartile, inverse-volatility weight using
the preceding 63 sessions, target 10% annualized volatility, and rebalance
every 20 sessions.  ``index_gate`` is a predeclared market-state ablation.
"""

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


def forecasts(frame):
    prices = frame.pivot(index="day", columns="symbol", values="close").sort_index()
    prices = prices.sort_index(axis=1)
    p = prices.to_numpy(dtype=float)
    if not np.isfinite(p).all() or (p <= 0).any():
        raise ValueError("incomplete or non-positive prices")
    logs = np.log(p)
    returns = np.diff(logs, axis=0)
    modes = {"equal", "momentum12_1", "momentum12_1_index_gate"}
    maps = {mode: {} for mode in modes}
    for i in range(252, len(p)):
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(p.shape[1]) * 1e-12
        sigma = np.sqrt(np.diag(cov))
        equal = np.full(p.shape[1], 0.95 / p.shape[1])
        score = logs[i - 21] - logs[i - 252]
        chosen = np.argsort(-score, kind="stable")[: max(1, math.ceil(p.shape[1] / 4))]
        raw = np.zeros(p.shape[1])
        raw[chosen] = 1.0 / np.maximum(sigma[chosen], 1e-12)
        momentum = np.minimum(0.2, 0.95 * raw / max(raw.sum(), 1e-12))
        market = np.exp(logs[i].mean())
        market_sma = np.exp(logs[i - 199 : i + 1].mean())
        for mode, target in (
            ("equal", equal),
            ("momentum12_1", momentum),
            ("momentum12_1_index_gate", momentum * float(market > market_sma)),
        ):
            target = target * min(1.0, 0.10 / max(np.sqrt(target @ cov @ target * 252), 1e-12))
            for j, symbol in enumerate(prices.columns):
                maps[mode][str(prices.index[i]), symbol] = dict(
                    target_weight=float(target[j]),
                    volatility=float(sigma[j]),
                    status="ok",
                )
    return maps


def main():
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(r["config"] for r in old["results"] if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1)
    windows = [(pool, meta["path"], "2025-09-01", "2026-09-01") for pool, meta in manifest.items()]
    for start, end in (("2022-09-01", "2023-09-01"), ("2023-09-01", "2024-09-01"), ("2024-09-01", "2025-09-01"), ("2022-09-01", "2025-09-01")):
        windows.append(("random10_temporal", "artifacts/research/annual-momentum/random10-temporal.parquet", start, end))
    rows = []
    dest = ROOT / "2026-09-21-vol-managed-momentum.json"
    for pool, path, start, end in windows:
        raw = pd.read_parquet(path)
        prior = sorted(raw.loc[raw.day < start, "day"].unique())[-273:]
        frame = raw[(raw.day >= prior[0]) & (raw.day < end)]
        mappings = forecasts(frame)
        for mode, mapping in mappings.items():
            for multiplier in (1, 2):
                costs = dict(cfg["costs"])
                for key in ("spread_bps", "slippage_bps", "commission_per_share", "minimum_commission", "sell_fee_bps"):
                    costs[key] *= multiplier
                config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": 20})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    run = simulate_positions(frame, config, start, end, daily_bars=True)
                row = dict(pool=pool, start=start, end_exclusive=end, candidate=mode, cost_multiplier=multiplier, config=run["config"], metrics=run["metrics"], contributions=run["contributions"], curve=run["curve"])
                rows.append(row)
                save_results(dest, rows)
                print(pool, start, mode, multiplier, round(run["metrics"]["return_pct"], 3), round(run["metrics"]["max_drawdown_pct"], 3), flush=True)
    save_results(dest, rows, completed=True)


if __name__ == "__main__":
    main()
