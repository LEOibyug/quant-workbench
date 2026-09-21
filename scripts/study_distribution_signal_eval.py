"""Separate causal distribution-aware signal closes from real execution prices."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from research_distribution_book import ResearchDistributionBook
from spinoff_marks import ChildMarks
from spinoff_signal import forward_index
from study_covariance_allocation import save_results
from study_distribution_expanded import EVENTS

ROOT = Path("docs/research-results")


def signal_frame(frame, events, marks):
    out = frame.copy(deep=True)
    for symbol, g in frame.groupby("symbol"):
        close = g.sort_values("day").set_index("day").close
        selected = [
            e
            for e in events
            if e["parent"] == symbol and close.index[0] <= e["day"] <= close.index[-1]
        ]
        if not selected:
            continue
        distributions = [
            dict(
                **e,
                child_close=marks.at(e["day"], [e["child"]], "close")[e["child"]],
                child_price_day=e["day"],
            )
            for e in selected
        ]
        index = forward_index(close, distributions)
        mask = out.symbol == symbol
        out.loc[mask, "close"] = out.loc[mask, "day"].map(index)
    return out


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    frame = pd.read_parquet("artifacts/research/alternate-history/daily.parquet")
    marks = ChildMarks(str(ROOT / "2026-09-21-spinoff-history.json"))
    rows = []
    path = ROOT / "2026-09-21-distribution-signal-eval.json"
    for start, end in [
        ("2022-09-01", "2023-09-01"),
        ("2023-09-01", "2024-09-01"),
        ("2024-09-01", "2025-09-01"),
        ("2022-09-01", "2025-09-01"),
    ]:
        f = frame[(frame.day >= start) & (frame.day < end)].copy()
        adjusted = signal_frame(f, EVENTS, marks)
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
            config = PositionConfig(**{**cfg, "costs": costs})
            for mode, signals in [("raw_signal", f), ("continuous_signal", adjusted)]:
                mapping = rule_forecasts(signals, config)
                book = ResearchDistributionBook(EVENTS, marks)
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    run = simulate_positions(
                        f, config, start, end, daily_bars=True, research_distributions=book
                    )
                rows.append(
                    dict(
                        start=start,
                        end_exclusive=end,
                        multiplier=mult,
                        method=mode,
                        config=run["config"],
                        metrics=run["metrics"],
                        curve=run["curve"],
                        contributions=run["contributions"],
                        distribution_audit=book.audit,
                    )
                )
                save_results(path, rows)
                print(
                    start,
                    end,
                    mult,
                    mode,
                    round(run["metrics"]["return_pct"], 4),
                    round(run["metrics"]["max_drawdown_pct"], 4),
                    flush=True,
                )
    save_results(path, rows, completed=True)


if __name__ == "__main__":
    main()
