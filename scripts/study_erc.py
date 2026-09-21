"""Frozen equal-risk-contribution portfolio allocation."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def erc_weights(cov):
    c = cov / np.mean(np.diag(cov))
    n = len(c)
    x = np.ones(n) / np.sqrt(n)
    for _ in range(2000):
        for j in range(n):
            other = c[j] @ x - c[j, j] * x[j]
            # Stable positive root when other is positive.
            root = np.sqrt(other**2 + 4 * c[j, j] / n)
            x[j] = 2 / n / (root + other) if other >= 0 else (root - other) / (2 * c[j, j])
        rc = x * (c @ x)
        if np.max(np.abs(rc - 1 / n)) < 1e-10:
            return x / x.sum()
    raise ValueError("ERC coordinate solver did not converge")


DIAGNOSTICS = []


def forecasts(frame):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    values = p.to_numpy()
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Invalid prices")
    returns = np.diff(np.log(values), axis=0)
    maps = {m: {} for m in ("equal", "inverse_vol", "erc")}
    for i in range(252, len(p)):
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(p.shape[1]) * 1e-12
        sigma = np.sqrt(np.diag(cov))
        inverse = 1 / sigma
        inverse = np.minimum(0.2, 0.95 * inverse / inverse.sum())
        erc = 0.95 * erc_weights(cov)
        erc *= min(1, 0.2 / erc.max())
        for mode, raw in [
            ("equal", np.minimum(0.2, np.full(p.shape[1], 0.95 / p.shape[1]))),
            ("inverse_vol", inverse),
            ("erc", erc),
        ]:
            target = raw * min(1, 0.1 / max(np.sqrt(raw @ cov @ raw * 252), 1e-12))
            if mode == "erc":
                rc = target * (cov @ target) / (target @ cov @ target)
                DIAGNOSTICS.append(
                    dict(
                        day=str(p.index[i]),
                        symbols=list(p.columns),
                        max_risk_share_error=float(np.max(np.abs(rc - 1 / len(rc)))),
                        gross=float(target.sum()),
                        max_weight=float(target.max()),
                        annual_vol=float(np.sqrt(target @ cov @ target * 252)),
                    )
                )
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
    dest = ROOT / "2026-09-21-erc.json"
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
    (ROOT / "2026-09-21-erc-targets.json").write_text(json.dumps(DIAGNOSTICS, indent=2))


if __name__ == "__main__":
    main()
