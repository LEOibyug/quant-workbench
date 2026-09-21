import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from spinoff_signal import forward_index  # noqa: E402


def test_distribution_corrects_return_without_rewriting_past():
    prices = pd.Series([100.0, 80.0, 88.0], index=["2024-04-01", "2024-04-02", "2024-04-03"])
    event = dict(
        id="test",
        day="2024-04-02",
        numerator=1,
        denominator=4,
        child_close=80.0,
        child_price_day="2024-04-02",
        verified=True,
    )
    result = forward_index(prices, [event])
    assert np.allclose(result, [100, 100, 110])
    for n in [1, 2]:
        assert result.iloc[:n].equals(forward_index(prices.iloc[:n], [event]))
    with pytest.raises(ValueError):
        forward_index(prices, [event, event])
    with pytest.raises(ValueError):
        forward_index(prices, [dict(event, child_price_day="2024-04-03")])
