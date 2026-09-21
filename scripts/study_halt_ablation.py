"""Research-only permanent portfolio halt ablation, with unchanged trading signals."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results
from study_tsmom import forecasts

ROOT = Path("docs/research-results")




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
    dest = ROOT / "2026-09-21-halt-ablation.json"
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
            config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": 20}).model_copy(
                update={"max_drawdown_pct": 100}
            )

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
                assert all(p["equity"] > 0 and not p["halted"] for p in result["curve"])
                record(method, result)
    save_results(dest, rows, completed=True)


if __name__ == "__main__":
    main()
