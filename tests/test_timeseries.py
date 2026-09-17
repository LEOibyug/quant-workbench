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
        if pending:
            observed_probabilities.append(pending[0]["probability"])
            revealed_labels.append(int(bars.iloc[index].close > pending[0]["close"]))
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


def test_return_head_updates_only_after_label_and_cost_gate_can_veto(bars):
    config = TimeSeriesConfig(enabled=True, k=5, max_iter=1, cost_aware=True)
    model = train_model(bars, config)
    offline = model.regressor.coef_.copy()
    for index in range(5):
        ctx = context(bars, index)
        ctx["round_trip_cost_bps"] = 10000
        model.predict(ctx)
    np.testing.assert_array_equal(model._states["NVDA"]["regressor"].coef_, offline)
    for index in range(5, 12):
        ctx = context(bars, index)
        ctx["round_trip_cost_bps"] = 10000
        decision = model.predict(ctx)
    assert decision["expected_return_bps"] is not None
    assert decision["required_edge_bps"] == 15001
    assert decision["allow_entry"] is False
    assert model.stats["return_mae_bps"] >= 0
    assert model.stats["zero_return_mae_bps"] >= 0
    np.testing.assert_array_equal(model.regressor.coef_, offline)
    assert not np.array_equal(model._states["NVDA"]["regressor"].coef_, offline)


def test_v1_saved_model_gets_default_cost_settings_without_return_head(bars):
    import pickle

    model = train_model(bars, TimeSeriesConfig(enabled=True, k=5, max_iter=1))
    del model.regressor
    for key in ("cost_aware", "cost_multiplier", "min_edge_bps"):
        model.config.__dict__.pop(key)
    restored = pickle.loads(pickle.dumps(model))
    assert restored.config.cost_aware is False
    assert restored.regressor is None
    for index in range(11):
        decision = restored.predict(context(bars, index))
    assert decision["probability"] is not None


def test_long_history_streaming_matches_batch_and_ignores_overnight_split(bars):
    from quant_workbench.timeseries import HistoricalContext, _long_rows

    tomorrow = bars.copy()
    tomorrow["timestamp"] += pd.Timedelta(days=1)
    tomorrow[["open", "high", "low", "close"]] /= 10
    joined = pd.concat([bars, tomorrow], ignore_index=True)
    expected = _long_rows(joined)
    history = HistoricalContext()
    for i, bar in enumerate(joined.to_dict("records")):
        history.observe(bar, bar["timestamp"])
        np.testing.assert_allclose(history.features()[0], expected.iloc[i], atol=1e-12)


def test_mlp_feedback_is_delayed_and_future_suffix_cannot_change_decisions(bars):
    import pickle

    config = TimeSeriesConfig(enabled=True, k=5, horizon=5, architecture="mlp", max_iter=1)
    model = train_model(bars, config)
    independent = pickle.loads(pickle.dumps(model))
    mutated = bars.copy()
    mutated.loc[21:, ["open", "high", "low", "close"]] *= 2
    initial = [x.copy() for x in model.estimator.coefs_]
    for index in range(21):
        decision = model.predict(context(bars, index))
        assert decision == independent.predict(context(mutated, index))
        assert model.stats["updates"] == max(0, index - 8)
        if index < 9:
            assert decision["feedback"] == [0] * 6
        if index == 9:
            expected_return = (bars.iloc[9].close / bars.iloc[4].close - 1) * 100
            assert decision["feedback"][3] == pytest.approx(expected_return)
            assert decision["feedback"][4] == pytest.approx(
                expected_return - decision["feedback"][2]
            )
    for a, b in zip(initial, model.estimator.coefs_, strict=True):
        np.testing.assert_array_equal(a, b)
    assert any(
        not np.array_equal(a, b)
        for a, b in zip(initial, model._states["NVDA"]["estimator"].coefs_, strict=True)
    )
    _, _, info = _training_samples(bars, config)
    assert ((info.target_timestamp - info.timestamp) == pd.Timedelta(minutes=5)).all()
    # All pending horizons are discarded after a data gap, along with stale error feedback.
    updates = model.stats["updates"]
    decision = model.predict(context(bars, 22))
    assert decision["feedback"] == [0] * 6
    assert model.stats["updates"] == updates


def test_history_seed_reads_only_prefix_and_does_not_consume_adaptation(bars):
    from quant_workbench.timeseries import _long_rows

    model = train_model(bars, TimeSeriesConfig(enabled=True, k=5, architecture="rbf", max_iter=1))
    next_day = bars.copy()
    next_day["timestamp"] += pd.Timedelta(days=1)
    model.seed_history(pd.concat([bars, next_day]), "2024-01-04")
    np.testing.assert_allclose(
        model._history["NVDA"].features()[0], _long_rows(bars).iloc[-1], atol=1e-12
    )
    assert model._states == {}
    assert model.stats["updates"] == 0
    decision = model.predict(context(next_day, 0))
    assert decision["observed_count"] == 1 and decision["warmup"]


@pytest.mark.parametrize("architecture", ["mlp", "rbf"])
def test_horizon15_multisymbol_serialization_and_overnight_reset(bars, architecture):
    import pickle

    other = bars.assign(symbol="AAPL")
    training = pd.concat([bars, other], ignore_index=True)
    config = TimeSeriesConfig(enabled=True, k=5, horizon=15, architecture=architecture, max_iter=1)
    model = train_model(training, config)
    restored = pickle.loads(pickle.dumps(model))
    for i in range(25):
        for symbol in ("NVDA", "AAPL"):
            left = model.predict(context(bars, i, symbol))
            right = restored.predict(context(bars, i, symbol))
            assert left == right
    assert model.stats["updates"] == 2 * 6
    updates = model.stats["updates"]
    tomorrow = bars.copy()
    tomorrow["timestamp"] += pd.Timedelta(days=1)
    decision = model.predict(context(tomorrow, 0))
    assert decision["feedback"] == [0] * 6
    assert model.stats["updates"] == updates
    assert not model._states["NVDA"]["pending"]
    assert len(model._history["NVDA"].returns) == 26
