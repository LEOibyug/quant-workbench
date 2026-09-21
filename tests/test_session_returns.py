"""Flat prices cannot create money; round-trip fees and impact reconcile."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_session_returns import simulate  # noqa: E402


def test_round_trip_cash_identity_on_flat_prices():
    prices = np.full((4, 3), 100.0)
    costs = dict(
        initial_cash=100000,
        spread_bps=2,
        slippage_bps=2,
        minimum_commission=1,
        commission_per_share=0,
        sell_fee_bps=0.3,
    )
    for mode, cycles in [("intraday", 4), ("overnight", 3), ("continuous", 1)]:
        free = simulate(prices, prices, mode, costs, 0)
        paid = simulate(prices, prices, mode, costs, 1)
        assert free["end_equity"] == pytest.approx(100000)
        assert paid["cycles"] == cycles and paid["orders"] == cycles * 6
        assert paid["end_equity"] == pytest.approx(100000 - paid["fees"] - paid["impact"])
        assert paid["end_equity"] < free["end_equity"]
