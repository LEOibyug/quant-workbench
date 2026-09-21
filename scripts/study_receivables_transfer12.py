"""Frozen receivables proxy: earlier-year diagnostic."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from prepare_transfer12_fundamentals import CACHE, EXCLUDED
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results
from study_receivables_strategy import forecasts

ROOT = Path("docs/research-results")


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    info = json.loads((ROOT / "2026-09-21-transfer12-fundamentals.json").read_text())
    identities = {
        s: {"identity_verified": r["current_identity_matched"]} for s, r in info["issuers"].items()
    }
    windows = [
        (
            "transfer12",
            "artifacts/research/transfer12-2026-09-21/daily.parquet",
            "2025-09-01",
            "2026-09-01",
        )
    ]
    for start, end in [
        ("2022-09-01", "2023-09-01"),
        ("2023-09-01", "2024-09-01"),
        ("2024-09-01", "2025-09-01"),
        ("2022-09-01", "2025-09-01"),
    ]:
        windows.append(
            (
                "transfer12_temporal",
                "artifacts/research/transfer12-temporal-2026-09-21/combined.parquet",
                start,
                end,
            )
        )
    rows = []
    diagnostics = []
    dest = ROOT / "2026-09-21-receivables-transfer12.json"
    for pool, path, start, end in windows:
        f = pd.read_parquet(path)
        prior = sorted(f.loc[f.day < start, "day"].unique())[-273:]
        frame = f if start == "2025-09-01" else f[(f.day >= prior[0]) & (f.day < end)]
        maps, coverage, _ = forecasts(frame, start, end, CACHE, identities, EXCLUDED)
        diagnostics.append(dict(start=start, end=end, coverage=coverage))
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
    (ROOT / "2026-09-21-receivables-transfer12-coverage.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
