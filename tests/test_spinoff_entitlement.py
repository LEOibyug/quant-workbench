import sys
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from spinoff_entitlement import allocate, mark  # noqa: E402


def test_fractional_claim_is_not_cash_and_entitlement_conserved():
    for ratio in [(1, 3), (1, 4), (1, 5)]:
        for shares in [0, 1, 2, 3, 5, 100, 101]:
            e = allocate(shares, *ratio)
            assert e.whole_shares + e.fractional_claim == Fraction(shares * ratio[0], ratio[1])
            assert 0 <= e.fractional_claim < 1
            value = mark(e, 54.13)
            assert value["cash_credit"] == 0
            assert value["whole_share_value"] + value[
                "fractional_receivable_value"
            ] == pytest.approx(shares * ratio[0] / ratio[1] * 54.13)
    with pytest.raises(ValueError):
        allocate(-1, 1, 3)
    with pytest.raises(TypeError):
        allocate(1.5, 1, 3)
