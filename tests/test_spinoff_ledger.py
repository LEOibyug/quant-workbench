import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from spinoff_ledger import DistributionLedger  # noqa: E402


def test_distribution_does_not_double_credit_or_invent_cash():
    ledger = DistributionLedger()
    ledger.apply("GEV2024", "GEV", 101, 1, 4)
    assert ledger.child_shares == {"GEV": 25}
    assert ledger.cash == 0
    assert ledger.value({"GEV": 100}) == 2525
    with pytest.raises(ValueError):
        ledger.apply("GEV2024", "GEV", 101, 1, 4)
    with pytest.raises(ValueError):
        ledger.value({})
    ledger.settle_fraction("GEV2024", 24)
    assert ledger.cash == 24
    assert ledger.value({"GEV": 100}) == 2524
    with pytest.raises(ValueError):
        ledger.settle_fraction("GEV2024", 24)
