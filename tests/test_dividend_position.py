"""Integrated cash, entitlement, and risk accounting, with no real-data tuning."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig, simulate_positions

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cash_dividend_book import CashDividendBook  # noqa: E402


def setup():
    days = schedule("2024-01-02", "2024-01-12").index.strftime("%Y-%m-%d")
    records = []
    for day in days:
        for symbol in ["A", "B"]:
            price = 94.0 if symbol == "A" and day >= "2024-01-09" else 100.0
            records.append(
                dict(
                    day=day,
                    symbol=symbol,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=100_000_000,
                )
            )
    config = PositionConfig(
        model="equal_weight",
        max_weight=0.5,
        tranche_weight=0.2,
        rebalance_days=1,
        stop_loss_pct=2,
        max_drawdown_pct=2,
        costs=dict(
            initial_cash=100000,
            spread_bps=0,
            slippage_bps=0,
            commission_per_share=0,
            minimum_commission=0,
            sell_fee_bps=0,
        ),
    )
    event = dict(
        id="synthetic",
        symbol="A",
        ex_date="2024-01-09",
        payable_date="2024-01-10",
        rate=6,
        currency="USD",
        kind="ordinary_cash",
        amount_basis="gross",
        verified=True,
        evidence=["Synthetic scenario"],
    )
    return pd.DataFrame(records), config, event


def test_dividend_enters_risk_and_contributions_but_cannot_be_spent_early():
    f, c, e = setup()
    raw = simulate_positions(f, c, "2024-01-02", "2024-01-12", daily_bars=True)
    r = simulate_positions(
        f, c, "2024-01-02", "2024-01-12", daily_bars=True, research_dividends=CashDividendBook([e])
    )
    assert raw["metrics"]["halted"] and not r["metrics"]["halted"]
    assert r["metrics"]["return_pct"] == pytest.approx(0)
    points = {p["date"]: p for p in r["curve"]}
    assert points["2024-01-08"]["cash"] == 0
    assert points["2024-01-09"]["dividends"]["receivable"] == 3000
    assert points["2024-01-10"]["cash"] == 3000
    assert not any(
        t["side"] == "buy" and "2024-01-09" <= t["date"] <= "2024-01-10" for t in r["trades"]
    )
    assert any(t["side"] == "buy" and t["date"] == "2024-01-11" for t in r["trades"])
    for p in r["curve"]:
        assert p["equity"] == pytest.approx(
            p["cash"]
            + sum(a["market_value"] for a in p["assets"].values())
            + p["dividends"]["receivable"]
        )
        assert p["equity"] - c.costs.initial_cash == pytest.approx(
            p["realized_pnl"] + p["unrealized_pnl"] + p["dividends"]["income"], abs=1e-8
        )
    assert sum(x["net_profit"] for x in r["contributions"]) == pytest.approx(
        r["metrics"]["final_equity"] - c.costs.initial_cash, abs=1e-8
    )
    a = points["2024-01-11"]["assets"]["A"]
    assert a["stop_dividend_credit_per_share"] * a["shares"] == pytest.approx(3000)
    unpaid = simulate_positions(
        f,
        c,
        "2024-01-02",
        "2024-01-12",
        daily_bars=True,
        research_dividends=CashDividendBook([{**e, "payable_date": "2024-01-20"}]),
    )
    assert unpaid["metrics"]["dividend_receivable"] == 3000
    assert unpaid["metrics"]["dividend_paid"] == 0
    assert unpaid["metrics"]["estimated_liquidation_return_pct"] is None
    assert unpaid["curve"][-1]["cash"] == 0


def test_empty_book_reproduces_existing_engine_and_reuse_is_rejected():
    f, c, e = setup()
    raw = simulate_positions(f, c, "2024-01-02", "2024-01-12", daily_bars=True)
    book = CashDividendBook([])
    r = simulate_positions(
        f, c, "2024-01-02", "2024-01-12", daily_bars=True, research_dividends=book
    )
    assert raw["metrics"] == {k: r["metrics"][k] for k in raw["metrics"]}
    assert raw["trades"] == r["trades"] and raw["contributions"] == r["contributions"]
    with pytest.raises(ValueError):
        simulate_positions(
            f, c, "2024-01-02", "2024-01-12", daily_bars=True, research_dividends=book
        )
