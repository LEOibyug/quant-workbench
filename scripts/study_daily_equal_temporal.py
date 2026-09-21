"""Fixed cross-period confirmation, full trading costs and target-exposure controls."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from study_olmar import forecasts

ROOT = Path("docs/research-results")


def main():
    original = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        x["config"]
        for x in original["results"]
        if x["method"] == "fixed_ensemble" and x["cost_multiplier"] == 1
    )
    sample = json.loads((ROOT / "2026-09-21-random-universe-protocol.json").read_text())
    source = Path("artifacts/research/multiscale-temporal-random10/daily.parquet")
    frame = pd.read_parquet(source)
    windows = [
        ("2022-09-01", "2023-09-01"),
        ("2023-09-01", "2024-09-01"),
        ("2024-09-01", "2025-09-01"),
        ("2022-09-01", "2025-09-01"),
    ]
    rows = []
    dest = ROOT / "2026-09-21-daily-equal-temporal.json"
    meta = dict(
        symbols=sample["symbols"],
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        rows=len(frame),
        protocol="2026-09-21-daily-equal-temporal-protocol.md",
    )
    for start, end in windows:
        prior = sorted(frame.loc[frame.day < start, "day"].unique())[-127:]
        assert len(prior) == 127
        segment = frame[(frame.day >= prior[0]) & (frame.day < end)]
        mapping = forecasts(segment)["equal"]
        for frequency in (1, 5):
            for multiplier in (1, 2):
                costs = dict(cfg["costs"])
                for key in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[key] *= multiplier
                config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": frequency})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    result = simulate_positions(segment, config, start, end, daily_bars=True)
                row = dict(
                    start=start,
                    end_exclusive=end,
                    method="equal_risk_scaled",
                    rebalance_days=frequency,
                    cost_multiplier=multiplier,
                    metrics=result["metrics"],
                    contributions=result["contributions"],
                    config=result["config"],
                    first_halt=next((p["date"] for p in result["curve"] if p["halted"]), None),
                    curve=[
                        {k: p[k] for k in ("date", "equity", "cash", "drawdown_pct")}
                        for p in result["curve"]
                    ],
                )
                rows.append(row)
                dest.write_text(
                    json.dumps(dict(status="running", metadata=meta, results=rows), indent=2)
                )
                print(
                    start,
                    end,
                    frequency,
                    multiplier,
                    round(row["metrics"]["return_pct"], 3),
                    round(row["metrics"]["max_drawdown_pct"], 3),
                    flush=True,
                )
    dest.write_text(json.dumps(dict(status="completed", metadata=meta, results=rows), indent=2))


if __name__ == "__main__":
    main()
