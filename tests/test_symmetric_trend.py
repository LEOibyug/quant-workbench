import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from quant_workbench.market_data import schedule
from study_symmetric_trend import forecasts, simulate


def sample():
    days = schedule("2023-01-01", "2024-01-01").index.strftime("%Y-%m-%d")
    n = len(days)
    p = 150 * np.exp(-np.arange(n) * 0.002)
    return pd.DataFrame(dict(day=days, symbol="TEST", open=p, close=p, volume=100000000))


def test_short_ledger_profits_on_decline_and_pays_carry():
    frame = sample()
    start = frame.day.iloc[130]
    end = frame.day.iloc[200]
    r = simulate(frame, "signed", start=start, end=end)
    assert r["return_pct"] > 0 and r["average_net_pct"] < 0
    assert r["carry_reserve"] > 0
    assert abs(sum(r["contributions"].values()) - r["return_pct"] * 1000) < 1e-6
    r2 = simulate(frame, "signed", 2, start=start, end=end)
    assert r2["return_pct"] < r["return_pct"]
    long = simulate(frame, "long_only", start=start, end=end)
    assert long["trades"] == 0 and long["return_pct"] == 0


def test_forecast_and_execution_do_not_read_future():
    frame = sample()
    cut = frame.day.iloc[180]
    base = forecasts(frame, "signed")
    changed = frame.copy()
    changed.loc[changed.day > cut, ["open", "close"]] *= 5
    new = forecasts(changed, "signed")
    for day in base:
        if day <= cut:
            assert base[day] == new[day]
    first = simulate(frame, "signed", start=frame.day.iloc[130], end=cut)
    second = simulate(changed, "signed", start=frame.day.iloc[130], end=cut)
    assert first == second
