"""Frozen abnormal dollar-volume activity with low-activity and unconditional controls."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def forecasts(frame):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    volume = frame.pivot(index="day", columns="symbol", values="volume").reindex(
        index=p.index, columns=p.columns
    )
    values = p.to_numpy()
    if (
        not np.isfinite(values).all()
        or (values <= 0).any()
        or not np.isfinite(volume.to_numpy()).all()
        or (volume <= 0).any().any()
    ):
        raise ValueError("Invalid prices or volume")
    end = (pd.Timestamp(p.index[-1]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cal = schedule(str(p.index[0]), end)
    if list(cal.index.strftime("%Y-%m-%d")) != list(p.index.astype(str)):
        raise ValueError("Missing market sessions")
    minutes = (cal.close - cal.open).dt.total_seconds().to_numpy() / 60
    activity = values * volume.to_numpy() / minutes[:, None]
    returns = np.diff(np.log(values), axis=0)
    expiry = {m: np.full(p.shape[1], -1) for m in ("high", "low")}
    maps = {m: {} for m in ("high", "low", "inverse_vol")}
    for i in range(252, len(p)):
        thresholds = np.quantile(activity[i - 252 : i], [0.05, 0.95], axis=0)
        for mode, trigger in [
            ("high", activity[i] > thresholds[1]),
            ("low", activity[i] < thresholds[0]),
        ]:
            new = trigger & (i >= expiry[mode])
            expiry[mode][new] = i + 21
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(p.shape[1]) * 1e-12
        vol = np.sqrt(np.diag(cov))
        for mode in maps:
            eligible = (
                np.ones(p.shape[1], dtype=bool) if mode == "inverse_vol" else i < expiry[mode]
            )
            raw = eligible / vol
            target = np.minimum(0.2, 0.95 * raw / raw.sum()) if raw.sum() > 0 else raw
            target *= min(1, 0.1 / max(np.sqrt(target @ cov @ target * 252), 1e-12))
            for j, s in enumerate(p.columns):
                maps[mode][str(p.index[i]), s] = dict(
                    target_weight=float(target[j]), volatility=float(vol[j]), status="ok"
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
    dest = ROOT / "2026-09-21-volume-event.json"
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
            config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": 1})

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
