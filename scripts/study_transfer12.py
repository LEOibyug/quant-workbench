"""New-stock transfer check of frozen allocation and signal methods."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import evaluate_alternate_universe as downloader
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from study_erc import forecasts
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")
SYMBOLS = "ABT ADP AMT BLK CME DUK LIN MDT SPGI UPS USB VZ".split()


def main():
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    prior = set(s for m in manifest.values() for s in m["symbols"])
    assert not prior.intersection(SYMBOLS)
    downloader.ROOT = Path("artifacts/research/transfer12-2026-09-21")
    downloader.SYMBOLS = SYMBOLS
    frame = downloader.download("2024-08-01", "2026-09-01")
    path = downloader.ROOT / "daily.parquet"
    (ROOT / "2026-09-21-transfer12-data.json").write_text(
        json.dumps(
            dict(
                path=str(path),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                symbols=SYMBOLS,
                rows=len(frame),
                full_corporate_action_audit=False,
                adjustment="raw",
                feed="sip",
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
    allocation = forecasts(frame)
    fixed = rule_forecasts(frame, PositionConfig(**cfg))
    rows = []
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
                r = simulate_positions(frame, config, "2025-09-01", "2026-09-01", daily_bars=True)
            rows.append(
                dict(
                    method=method,
                    cost_multiplier=mult,
                    pool="transfer12",
                    start="2025-09-01",
                    end_exclusive="2026-09-01",
                    config=r["config"],
                    metrics=r["metrics"],
                    curve=r["curve"],
                    contributions=r["contributions"],
                )
            )
            save_results(ROOT / "2026-09-21-transfer12.json", rows)
            print(
                method,
                mult,
                r["metrics"]["return_pct"],
                r["metrics"]["max_drawdown_pct"],
                flush=True,
            )
    save_results(ROOT / "2026-09-21-transfer12.json", rows, completed=True)


if __name__ == "__main__":
    main()
