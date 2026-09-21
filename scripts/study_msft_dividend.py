"""Issuer-verified MSFT-only correction; other stocks still omit dividends."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from cash_dividend_book import CashDividendBook
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def dividend_signal(frame, events):
    out = frame.copy(deep=True)
    close = frame[frame.symbol == "MSFT"].sort_values("day").set_index("day").close
    income = pd.Series(0.0, index=close.index)
    seen = set()
    for e in events:
        day = e["ex_date"]
        if not close.index[0] < day <= close.index[-1]:
            continue
        if not e["verified"] or e["currency"] != "USD" or e["announcement_date"] >= day:
            raise ValueError("Verified prior declaration required")
        if day not in close.index or day in seen:
            raise ValueError("Missing or duplicate ex-date")
        seen.add(day)
        income.loc[day] = float(e["rate"])
    growth = (close + income) / close.shift(1)
    growth.iloc[0] = 1
    index = close.iloc[0] * growth.cumprod()
    mask = out.symbol == "MSFT"
    out.loc[mask, "close"] = out.loc[mask, "day"].map(index)
    return out


def main():
    source = json.loads((ROOT / "2026-09-22-msft-dividends.json").read_text())
    events = source["events"]
    frame = pd.read_parquet("artifacts/research/annual-momentum/original20.parquet")
    adjusted = dividend_signal(frame, events)
    before = dividend_signal(frame[frame.day < "2026-01-01"], events)
    pd.testing.assert_frame_equal(adjusted[adjusted.day < "2026-01-01"], before)
    active = [e for e in events if "2025-09-01" <= e["ex_date"] < "2026-09-01"]
    old = json.loads((ROOT / "2026-09-21-vix-budget.json").read_text())["results"]
    rows = []
    checks = []
    for cost in [1, 2]:
        baseline = next(
            r
            for r in old
            if r["pool"] == "original20"
            and r["method"] == "baseline"
            and r["cost_multiplier"] == cost
        )
        config = PositionConfig(**baseline["config"])
        for mode in ["raw", "msft_book", "msft_book_signal"]:
            signal = adjusted if mode == "msft_book_signal" else frame
            mapping = rule_forecasts(signal, config)
            book = CashDividendBook(active) if mode != "raw" else None
            with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                r = simulate_positions(
                    frame,
                    config,
                    "2025-09-01",
                    "2026-09-01",
                    daily_bars=True,
                    research_dividends=book,
                )
            if mode == "raw":
                assert r["metrics"] == baseline["metrics"]
                assert r["contributions"] == baseline["contributions"]
            for p in r["curve"]:
                d = p.get("dividends", {})
                np.testing.assert_allclose(
                    p["equity"],
                    p["cash"]
                    + sum(a["market_value"] for a in p["assets"].values())
                    + d.get("receivable", 0),
                    rtol=0,
                    atol=1e-7,
                )
            np.testing.assert_allclose(
                sum(x["net_profit"] for x in r["contributions"]),
                r["metrics"]["final_equity"] - config.costs.initial_cash,
                rtol=0,
                atol=1e-7,
            )
            checks.append(
                dict(
                    mode=mode,
                    cost_multiplier=cost,
                    equity_and_contribution_consistent=True,
                    raw_control_exact=mode == "raw",
                )
            )
            rows.append(
                dict(
                    pool="original20",
                    method=mode,
                    cost_multiplier=cost,
                    config=r["config"],
                    metrics=r["metrics"],
                    curve=r["curve"],
                    contributions=r["contributions"],
                    dividend_audit=r.get("research_dividends"),
                    assumptions=r["assumptions"],
                )
            )
            print(
                mode,
                cost,
                r["metrics"]["return_pct"],
                r["metrics"].get("dividend_income"),
                flush=True,
            )
    save_results(ROOT / "2026-09-22-msft-dividend-study.json", rows, completed=True)
    (ROOT / "2026-09-22-msft-dividend-checks.json").write_text(
        json.dumps(dict(prefix_invariance=True, checks=checks, active_events=active), indent=2)
        + "\n"
    )


if __name__ == "__main__":
    main()
