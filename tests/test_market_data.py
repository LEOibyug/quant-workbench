import pandas as pd
import pytest
from quant_workbench.market_data import demo_data, normalize_bars, session_minutes


def test_calendar_observes_dst_and_thanksgiving_early_close():
    assert len(session_minutes("2024-11-29", "2024-11-30")) == 210
    assert str(session_minutes("2024-03-08", "2024-03-09")[0]) == "2024-03-08 14:31:00+00:00"
    assert str(session_minutes("2024-03-11", "2024-03-12")[0]) == "2024-03-11 13:31:00+00:00"


def test_import_preserves_explicit_timezone_and_canonical_order():
    frame = demo_data().iloc[:3].copy()
    frame["timestamp"] = frame.timestamp.dt.tz_convert("America/New_York").astype(str)
    result = normalize_bars(frame.iloc[::-1])
    assert str(result.timestamp.dt.tz) == "UTC"
    assert result.timestamp.is_monotonic_increasing


@pytest.mark.parametrize("problem", ["duplicate", "naive", "ohlc", "nan", "off_session"])
def test_bad_data_is_rejected_instead_of_silently_repaired(problem):
    frame = demo_data().iloc[:3].copy()
    if problem == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    elif problem == "naive":
        frame["timestamp"] = frame.timestamp.dt.tz_localize(None).astype(str)
    elif problem == "ohlc":
        frame.loc[frame.index[0], "high"] = 0.1
    elif problem == "nan":
        frame.loc[frame.index[0], "volume"] = float("nan")
    else:
        frame.loc[frame.index[0], "timestamp"] -= pd.Timedelta(hours=6)
    with pytest.raises(ValueError):
        normalize_bars(frame)
