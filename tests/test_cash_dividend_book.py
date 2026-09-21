import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cash_dividend_book import CashDividendBook  # noqa: E402


def event(**extra):
    return dict(
        dict(
            id="one",
            symbol="A",
            ex_date="2024-02-09",
            payable_date="2024-02-15",
            rate="0.24",
            currency="USD",
            kind="ordinary_cash",
            amount_basis="gross",
            verified=True,
            evidence=["synthetic case"],
        ),
        **extra,
    )


def test_entitlement_survives_sale_and_is_not_cash_before_payment():
    b = CashDividendBook([event()])
    assert b.before_open("2024-02-09", {"A": 10}) == Decimal("2.40")
    # Mechanical ex-dividend price drop is offset by a claim, not spendable cash.
    assert Decimal("99.76") * 10 + b.receivable == Decimal("1000")
    assert b.after_close("2024-02-09") == 0
    assert b.before_open("2024-02-15", {"A": 0}) == Decimal("2.40")
    assert b.after_close("2024-02-15") == Decimal("2.40")
    assert b.receivable == 0
    with pytest.raises(ValueError):
        b.after_close("2024-02-15")
    b.before_open("2024-02-16", {"A": 0})
    assert b.after_close("2024-02-16") == 0
    # Buying on ex-date after zero preceding holdings gets no entitlement.
    newcomer = CashDividendBook([event()])
    newcomer.before_open("2024-02-09", {"A": 0})
    newcomer.after_close("2024-02-09")
    newcomer.before_open("2024-02-15", {"A": 10})
    assert newcomer.after_close("2024-02-15") == 0


def test_ambiguous_unverified_and_missing_snapshots_rejected_before_mutation():
    for events in [
        [event(verified=False)],
        [event(currency=None)],
        [event(special=True)],
        [event(), event(id="different_cusip")],
    ]:
        with pytest.raises(ValueError):
            CashDividendBook(events)
    b = CashDividendBook([event(), event(id="two", symbol="B")])
    with pytest.raises(ValueError):
        b.before_open("2024-02-09", {"A": 10})
    assert b.total_earned == 0 and not b.claims
    b.before_open("2024-02-08", {"A": 10, "B": 10})
    b.after_close("2024-02-08")
    with pytest.raises(ValueError):
        b.before_open("2024-02-12", {"A": 10, "B": 10})
