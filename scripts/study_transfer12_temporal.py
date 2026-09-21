"""Frozen earlier-window checks on the additional twelve-stock universe."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import evaluate_alternate_universe as downloader
from quant_workbench.daily_data import normalize_daily
from quant_workbench.market_data import schedule
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from study_erc import forecasts
from study_covariance_allocation import save_results
from study_transfer12 import SYMBOLS, ROOT


def main():
    downloader.SYMBOLS = SYMBOLS
    downloader.ROOT = Path("artifacts/research/transfer12-temporal-2026-09-21")
    prior = downloader.download("2021-08-01", "2024-08-01")
    recent = pd.read_parquet("artifacts/research/transfer12-2026-09-21/daily.parquet")
    recent = recent[(recent.day >= "2024-08-01") & (recent.day < "2025-09-01")]
    all_data = normalize_daily(pd.concat([prior, recent], ignore_index=True))
    expected = set(schedule("2021-08-01", "2025-09-01").index.strftime("%Y-%m-%d"))
    for s, g in all_data.groupby("symbol"):
        assert set(g.day) == expected
        gap = g.sort_values("day").open.to_numpy()[1:] / g.sort_values("day").close.to_numpy()[:-1]
        if ((gap < 0.65) | (gap > 1.5)).any():
            raise ValueError(f"{s}: unresolved price discontinuity")
    dest = downloader.ROOT / "combined.parquet"
    all_data.to_parquet(dest, index=False)
    (ROOT / "2026-09-21-transfer12-temporal-data.json").write_text(
        json.dumps(
            dict(
                path=str(dest),
                sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                symbols=SYMBOLS,
                rows=len(all_data),
                adjustment="raw",
                full_corporate_action_audit=False,
            ),
            indent=2,
        )
    )
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    output = ROOT / "2026-09-21-transfer12-temporal.json"
    rows = []
    for start, end in [
        ("2022-09-01", "2023-09-01"),
        ("2023-09-01", "2024-09-01"),
        ("2024-09-01", "2025-09-01"),
        ("2022-09-01", "2025-09-01"),
    ]:
        history = sorted(all_data.loc[all_data.day < start, "day"].unique())[-273:]
        frame = all_data[(all_data.day >= history[0]) & (all_data.day < end)]
        allocation = forecasts(frame)
        fixed = rule_forecasts(frame, PositionConfig(**cfg))
        for method, mapping, days in [
            ("fixed_ensemble", fixed, 5),
            ("erc", allocation["erc"], 20),
            ("equal20", allocation["equal"], 20),
            ("equal5", allocation["equal"], 5),
        ]:
            for mult in (1, 2):
                costs = dict(cfg["costs"])
                for k in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[k] *= mult
                config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": days})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    r = simulate_positions(frame, config, start, end, daily_bars=True)
                rows.append(
                    dict(
                        method=method,
                        start=start,
                        end_exclusive=end,
                        cost_multiplier=mult,
                        config=r["config"],
                        metrics=r["metrics"],
                        curve=r["curve"],
                        contributions=r["contributions"],
                    )
                )
                save_results(output, rows)
                print(
                    start,
                    end,
                    method,
                    mult,
                    round(r["metrics"]["return_pct"], 4),
                    round(r["metrics"]["max_drawdown_pct"], 4),
                    flush=True,
                )
    save_results(output, rows, completed=True)


if __name__ == "__main__":
    main()
