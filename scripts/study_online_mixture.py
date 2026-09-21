"""Finite expert wealth mixing with actual net-account expert feedback."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def mixture_maps(experts, initial):
    curves = [r["curve"] for r in experts]
    if [p["date"] for p in curves[0]] != [p["date"] for p in curves[1]]:
        raise ValueError("Expert calendar mismatch")
    output = {"wealth_mix": {}, "static_mix": {}}
    for points in zip(*curves, strict=True):
        wealth = np.array([p["equity"] for p in points] + [initial])
        if not np.isfinite(wealth).all() or (wealth <= 0).any():
            raise ValueError("Invalid expert equity")
        for method, q in [("wealth_mix", wealth / wealth.sum()), ("static_mix", np.ones(3) / 3)]:
            for symbol in points[0]["assets"]:
                target = sum(
                    q[k] * p["assets"][symbol]["target_weight"] for k, p in enumerate(points)
                )
                output[method][points[0]["date"], symbol] = {
                    "target_weight": float(target),
                    "volatility": 0.01,
                    "status": "ok",
                }
    return output


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
    dest = ROOT / "2026-09-21-online-mixture.json"
    for pool, path, start, end in windows:
        f = pd.read_parquet(path)
        prior = sorted(f.loc[f.day < start, "day"].unique())[-273:]
        frame = f[(f.day >= prior[0]) & (f.day < end)]
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
            experts = []

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

            for method in ("fixed_ensemble", "equal_weight"):
                expert_config = PositionConfig(**{**cfg, "costs": costs, "model": method})
                result = simulate_positions(frame, expert_config, start, end, daily_bars=True)
                experts.append(result)
                record(method, result)
            for method, mapping in mixture_maps(experts, costs["initial_cash"]).items():
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    result = simulate_positions(frame, config, start, end, daily_bars=True)
                record(method, result)
    save_results(dest, rows, completed=True)


if __name__ == "__main__":
    main()
