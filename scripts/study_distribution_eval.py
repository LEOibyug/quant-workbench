"""Compare raw and verified in-window spinoff accounting on alternate-pool windows."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from research_distribution_book import ResearchDistributionBook
from spinoff_marks import ChildMarks
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")
EVENTS = [
    dict(
        id="GEHC-2023",
        parent="GE",
        child="GEHC",
        day="2023-01-04",
        numerator=1,
        denominator=3,
        verified=True,
    ),
    dict(
        id="GEV-2024",
        parent="GE",
        child="GEV",
        day="2024-04-02",
        numerator=1,
        denominator=4,
        verified=True,
    ),
]


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    source = Path("artifacts/research/alternate-history/daily.parquet")
    frame = pd.read_parquet(source)
    rows = []
    out = ROOT / "2026-09-21-distribution-eval.json"
    for start, end in [("2023-09-01", "2024-09-01"), ("2024-09-01", "2025-09-01")]:
        f = frame[(frame.day >= start) & (frame.day < "2025-09-01")]
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
            for method in ("fixed_ensemble", "equal_weight"):
                config = PositionConfig(**{**cfg, "model": method, "costs": costs})
                maps = rule_forecasts(f, config) if method == "fixed_ensemble" else {}
                with patch("quant_workbench.position.daily_forecasts", return_value=maps):
                    raw = simulate_positions(f, config, start, end, daily_bars=True)
                for variant, result in [("raw", raw)]:
                    rows.append(
                        dict(
                            start=start,
                            end_exclusive=end,
                            multiplier=mult,
                            method=method,
                            variant=variant,
                            metrics=result["metrics"],
                            curve=result["curve"],
                            contributions=result["contributions"],
                            config=result["config"],
                        )
                    )
                book = ResearchDistributionBook(
                    EVENTS, ChildMarks("docs/research-results/2026-09-21-spinoff-history.json")
                )
                with patch("quant_workbench.position.daily_forecasts", return_value=maps):
                    corrected = simulate_positions(
                        f, config, start, end, daily_bars=True, research_distributions=book
                    )
                rows.append(
                    dict(
                        start=start,
                        end_exclusive=end,
                        multiplier=mult,
                        method=method,
                        variant="with_distribution",
                        metrics=corrected["metrics"],
                        curve=corrected["curve"],
                        contributions=corrected["contributions"],
                        config=corrected["config"],
                    )
                )
                save_results(out, rows)
                print(
                    start,
                    method,
                    mult,
                    raw["metrics"]["return_pct"],
                    corrected["metrics"]["return_pct"],
                    flush=True,
                )
    save_results(out, rows, completed=True)


if __name__ == "__main__":
    main()
