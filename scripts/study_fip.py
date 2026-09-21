"""Conditional information continuity hypothesis; frozen 72-account development diagnostic."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from information_continuity import forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

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
    windows.append(
        (
            "transfer12",
            "artifacts/research/transfer12-2026-09-21/daily.parquet",
            "2025-09-01",
            "2026-09-01",
        )
    )
    for pool, path in [
        ("random10_temporal", "artifacts/research/annual-momentum/random10-temporal.parquet"),
        (
            "transfer12_temporal",
            "artifacts/research/transfer12-temporal-2026-09-21/combined.parquet",
        ),
    ]:
        for start, end in [
            ("2022-09-01", "2023-09-01"),
            ("2023-09-01", "2024-09-01"),
            ("2024-09-01", "2025-09-01"),
            ("2022-09-01", "2025-09-01"),
        ]:
            windows.append((pool, path, start, end))
    rows = []
    diagnostics = []
    dest = ROOT / "2026-09-22-fip.json"
    for pool, path, start, end in windows:
        f = pd.read_parquet(path)
        prior = sorted(f.loc[f.day < start, "day"].unique())[-273:]
        frame = f if start == "2025-09-01" else f[(f.day >= prior[0]) & (f.day < end)]
        assert not frame.duplicated(["day", "symbol"]).any()
        pivot = frame.pivot(index="day", columns="symbol", values="close")
        assert pivot.notna().all().all() and (pivot > 0).all().all()
        maps, coverage, _ = forecasts(frame, start, end)
        for decision in coverage:
            groups = decision["selected"]
            assert not set(groups["continuous"]) & set(groups["discrete"])
            for mapping in maps.values():
                weights = [
                    v["target_weight"] for (day, _), v in mapping.items() if day == decision["day"]
                ]
                assert all(0 <= w <= 0.2 + 1e-10 for w in weights)
                assert sum(weights) <= decision["budget"] + 1e-10
        diagnostics.append(dict(pool=pool, start=start, end=end, coverage=coverage))
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
                save_results(dest, rows, completed=False)
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
    (ROOT / "2026-09-22-fip-coverage.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
