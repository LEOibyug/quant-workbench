"""Fixed cross-period confirmation, full trading costs and target-exposure controls."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import evaluate_alternate_universe as downloader
from quant_workbench.position import PositionConfig, simulate_positions
from study_symmetric_trend import forecasts

ROOT = Path("docs/research-results")


def main():
    original = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        x["config"]
        for x in original["results"]
        if x["method"] == "fixed_ensemble" and x["cost_multiplier"] == 1
    )
    sample = json.loads((ROOT / "2026-09-21-random-universe-protocol.json").read_text())
    downloader.SYMBOLS = sample["symbols"]
    downloader.ROOT = Path("artifacts/research/multiscale-temporal-random10")
    frame = downloader.download("2022-02-28", "2025-09-01")
    windows = [
        ("2022-09-01", "2023-09-01"),
        ("2023-09-01", "2024-09-01"),
        ("2024-09-01", "2025-09-01"),
        ("2022-09-01", "2025-09-01"),
    ]
    rows = []
    dest = ROOT / "2026-09-21-multiscale-temporal.json"
    meta = dict(
        symbols=sample["symbols"],
        sha256=hashlib.sha256((downloader.ROOT / "daily.parquet").read_bytes()).hexdigest(),
        rows=len(frame),
        protocol="2026-09-21-multiscale-temporal-protocol.md",
    )
    for start, end in windows:
        prior = sorted(frame.loc[frame.day < start, "day"].unique())[-127:]
        assert len(prior) == 127
        segment = frame[(frame.day >= prior[0]) & (frame.day < end)]
        candidate = forecasts(segment, "long_only")
        risk = forecasts(segment, "risk_only")
        equal = {
            day: {s: sum(weights.values()) / len(weights) for s in weights}
            for day, weights in candidate.items()
        }
        for method in ("multiscale", "fixed_ensemble", "risk_only", "gross_matched_equal"):
            mapping = None
            if method != "fixed_ensemble":
                chosen = {"multiscale": candidate, "risk_only": risk, "gross_matched_equal": equal}[
                    method
                ]
                mapping = {
                    (d, s): dict(target_weight=w, volatility=0.01, status="ok")
                    for d, g in chosen.items()
                    for s, w in g.items()
                }
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
                config = PositionConfig(**{**cfg, "costs": costs})
                if mapping is None:
                    result = simulate_positions(segment, config, start, end, daily_bars=True)
                else:
                    with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                        result = simulate_positions(segment, config, start, end, daily_bars=True)
                row = dict(
                    start=start,
                    end_exclusive=end,
                    method=method,
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
                    method,
                    multiplier,
                    round(row["metrics"]["return_pct"], 3),
                    round(row["metrics"]["max_drawdown_pct"], 3),
                    flush=True,
                )
    dest.write_text(json.dumps(dict(status="completed", metadata=meta, results=rows), indent=2))


if __name__ == "__main__":
    main()
