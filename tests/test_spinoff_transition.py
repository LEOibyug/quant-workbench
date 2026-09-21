import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from spinoff_transition import DistributionState  # noqa: E402


def test_before_open_risk_uses_combined_equity_and_transferred_basis():
    book = DistributionState()
    event = dict(id="split", child="CHILD", numerator=1, denominator=4, verified=True)
    result = book.apply_before_risk(event, 101, 100.0, 80.0, 80.0)
    assert result["parent_basis"] == 80
    assert result["cash_change"] == 0 and result["parent_shares"] == 101
    mark = book.mark({"CHILD": 80.0})
    assert 101 * 80 + mark["market_value"] == 101 * 100
    assert 101 * result["parent_basis"] + sum(book.child_cost.values()) == 101 * 100
    assert 101 * (80 - result["parent_basis"]) + mark["unrealized_pnl"] == 0
    # Mechanical ex-distribution loss should not cause either a 10% account or stock stop.
    assert 101 * 80 + mark["market_value"] > 101 * 100 * 0.9
    assert 80 > result["parent_basis"] * 0.9
    before = copy.deepcopy(book)
    with pytest.raises(ValueError):
        book.apply_before_risk(event, 101, 100.0, 80.0, 80.0)
    assert book == before
    with pytest.raises(ValueError):
        book.apply_before_risk(dict(event, id="bad"), 101, 100.0, 80.0, float("nan"))
    assert book == before
    with pytest.raises(ValueError):
        book.mark({})
