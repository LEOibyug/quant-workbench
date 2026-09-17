import copy

import numpy as np
import pandas as pd
import pytest
from quant_workbench.timeseries import (
    TimeSeriesConfig,
    _feature_rows,
    _training_samples,
    train_model,
)


@pytest.fixture
def bars():
    rng = np.random.default_rng(17)
    timestamps = pd.date_range("2024-01-03T14:31:00Z", periods=390, freq="min")
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, len(timestamps))))
    opening = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": "NVDA",
            "open": opening,
            "high": np.maximum(opening, close) + 0.1,
            "low": np.minimum(opening, close) - 0.1,
            "close": close,
            "volume": rng.integers(1000, 10000, len(timestamps)),
        }
    )


def context(frame, index, symbol="NVDA"):
    recent = frame.iloc[max(0, index - 59) : index + 1].drop(columns="symbol").copy()
    recent["timestamp"] = recent.timestamp.map(lambda t: t.isoformat())
    return {
        "symbol": symbol,
        "timestamp": frame.iloc[index].timestamp.isoformat(),
        "recent_bars": recent.to_dict("records"),
        "technical_signal": "sma",
        "stock_features": {},
    }


def test_features_prefix_invariant_labels_inside_train_and_session(bars):
    config = TimeSeriesConfig()
    pd.testing.assert_frame_equal(_feature_rows(bars).iloc[:200], _feature_rows(bars.iloc[:200]))
    _, _, info = _training_samples(bars.iloc[:200], config)
    assert info.timestamp.min() == bars.iloc[29].timestamp
    assert info.timestamp.max() == bars.iloc[198].timestamp
    assert info.target_timestamp.max() == bars.iloc[199].timestamp
    tomorrow = bars.copy()
    tomorrow["timestamp"] += pd.Timedelta(days=1)
    _, _, joined = _training_samples(pd.concat([bars, tomorrow]), config)
    assert len(joined) == 2 * (390 - 30)
    assert (joined.timestamp.dt.date == joined.target_timestamp.dt.date).all()


def test_online_warmup_matured_labels_and_scaler_frozen(bars):
    config = TimeSeriesConfig(enabled=True, k=5, max_iter=1)
    model = train_model(bars, config)
    initial_scaler = model.scaler.mean_.copy()
    initial_weights = model.estimator.coef_.copy()
    observed_probabilities, revealed_labels = [], []
    for index in range(11):
        pending = model._states.get("NVDA", {}).get("pending")
        if pending is not None:
            observed_probabilities.append(pending["probability"])
            revealed_labels.append(int(bars.iloc[index].close > pending["close"]))
        decision = model.predict(context(bars, index))
        assert decision["warmup"] == (index < 10)
        if index < 10:
            assert decision["allow_entry"] is False
        if index < 10:
            assert decision["probability"] is None
        else:
            assert 0 <= decision["probability"] <= 1
        assert model.stats["updates"] == max(0, index - 4)
    np.testing.assert_array_equal(model.scaler.mean_, initial_scaler)
    np.testing.assert_array_equal(model.estimator.coef_, initial_weights)
    assert not np.array_equal(model._states["NVDA"]["estimator"].coef_, initial_weights)
    assert model.stats["evaluated_predictions"] == 6
    assert 0 <= model.stats["accuracy"] <= 1
    expected_brier = np.mean((np.array(observed_probabilities) - np.array(revealed_labels)) ** 2)
    assert model.stats["brier_score"] == pytest.approx(expected_brier)
    assert model.__getstate__()["_states"] == {}
    checkpoint = model.checkpoint_state()
    assert checkpoint["states"]["NVDA"]["count"] == 11
    np.testing.assert_array_equal(
        checkpoint["states"]["NVDA"]["estimator"].coef_,
        model._states["NVDA"]["estimator"].coef_,
    )
    checkpoint["states"]["NVDA"]["count"] = -1
    assert model._states["NVDA"]["count"] == 11
    assert model.metadata["last_target_time"] == bars.iloc[-1].timestamp.isoformat()


def test_future_input_cannot_change_prefix_and_symbols_are_independent(bars):
    model = train_model(bars, TimeSeriesConfig(enabled=True, k=5, max_iter=1))
    independent = copy.deepcopy(model)
    for index in range(25):
        model.predict(context(bars, index, "NVDA"))
    for index in range(12):
        left = model.predict(context(bars, index, "AAPL"))
        right = independent.predict(context(bars, index, "AAPL"))
        assert left == right
    updates = model.stats["updates"]
    future = context(bars, 26)
    future["timestamp"] = bars.iloc[25].timestamp.isoformat()
    assert model.predict(future)["allow_entry"] is False
    assert model.stats["updates"] == updates


def test_gap_discards_pending_label_and_rebuilds_window(bars):
    model = train_model(bars, TimeSeriesConfig(enabled=True, k=5, max_iter=1))
    for index in range(12):
        model.predict(context(bars, index))
    updates = model.stats["updates"]
    after_gap = model.predict(context(bars, 13))
    assert after_gap["probability"] is None
    assert model.stats["updates"] == updates
    for index in range(14, 18):
        decision = model.predict(context(bars, index))
    assert decision["probability"] is not None
    assert model.stats["updates"] == updates
    model.predict(context(bars, 18))
    assert model.stats["updates"] == updates + 1
    with pytest.raises(ValueError, match="有效训练样本不足"):
        train_model(bars.iloc[:60], TimeSeriesConfig())
