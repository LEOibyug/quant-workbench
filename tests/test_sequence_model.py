import copy
import pickle

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from quant_workbench.sequence_features import SequenceHistory  # noqa: E402
from quant_workbench.sequence_model import (  # noqa: E402
    SequenceNetwork,
    select_device,
    training_sequences,
)
from quant_workbench.timeseries import TimeSeriesConfig, train_model  # noqa: E402


@pytest.fixture
def bars():
    rng = np.random.default_rng(21)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, 390)))
    opening = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        dict(
            timestamp=pd.date_range("2024-01-03T14:31Z", periods=390, freq="min"),
            symbol="NVDA",
            open=opening,
            high=np.maximum(opening, close) + 0.1,
            low=np.minimum(opening, close) - 0.1,
            close=close,
            volume=rng.integers(1000, 10000, 390),
        )
    )


def ctx(frame, i, symbol="NVDA"):
    row = frame.iloc[i].to_dict()
    return dict(
        symbol=symbol,
        timestamp=row["timestamp"].isoformat(),
        recent_bars=[row],
        round_trip_cost_bps=8,
    )


def test_sequence_prefix_invariance_completed_candles_and_gap(bars):
    config = TimeSeriesConfig(architecture="gru", k=5, horizon=5, min_training_samples=50)
    values, info = training_sequences(bars, config)
    prefix, early = training_sequences(bars.iloc[:200], config)
    assert info.iloc[0].timestamp == bars.iloc[4].timestamp
    assert (early.target_timestamp <= bars.iloc[199].timestamp).all()
    for key in values:
        np.testing.assert_array_equal(values[key][: len(early)], prefix[key])
    history = SequenceHistory(5)
    for row in bars.iloc[:4].to_dict("records"):
        history.observe(row, row["timestamp"])
    assert len(history.long) == 0
    row = bars.iloc[4].to_dict()
    history.observe(row, row["timestamp"])
    assert len(history.long) == 1
    for row in bars.iloc[6:10].to_dict("records"):
        history.observe(row, row["timestamp"])
    assert len(history.long) == 1  # incomplete 5-minute group discarded


def test_offline_background_matches_streaming_across_symbols_and_gaps(bars):
    from quant_workbench.timeseries import HistoricalContext

    frame = pd.concat([
        bars.iloc[:150], bars.iloc[160:300],
        bars.assign(timestamp=bars.timestamp + pd.Timedelta(days=1)),
        bars.assign(symbol="AAPL"),
    ], ignore_index=True)
    values, info = training_sequences(frame, TimeSeriesConfig(k=5, horizon=5))
    expected = {}
    for symbol, group in frame.groupby("symbol"):
        memory = HistoricalContext()
        for bar in group.sort_values("timestamp").to_dict("records"):
            memory.observe(bar, bar["timestamp"])
            expected[(symbol, bar["timestamp"])] = memory.features().ravel()
    reference = np.array([expected[(row.symbol, row.timestamp)] for row in info.itertuples()])
    np.testing.assert_allclose(values["context"][:, :6], reference, rtol=1e-6, atol=1e-7)


def test_device_selection_and_causal_network_masks_padding(monkeypatch):
    import torch

    monkeypatch.setenv("QUANT_TORCH_DEVICE", "auto")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert select_device() == "cuda"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert select_device() == "cpu"  # MPS support dropped; CUDA ecosystem only.
    monkeypatch.setenv("QUANT_TORCH_DEVICE", "cuda")
    with pytest.raises(ValueError, match="不可用"):
        select_device()
    net = SequenceNetwork().eval()
    short = torch.randn(1, 5, 7)
    long = torch.randn(1, 78, 7)
    length = torch.tensor([3])
    context = torch.zeros(1, 12)
    left = net(short, long, length, context)
    long[:, 3:] = 999
    right = net(short, long, length, context)
    for a, b in zip(left, right, strict=True):
        torch.testing.assert_close(a, b)


def test_gru_delay_replay_portable_artifact_and_stock_isolation(bars, monkeypatch):
    import torch

    monkeypatch.setenv("QUANT_TORCH_DEVICE", "cpu")
    config = TimeSeriesConfig(
        enabled=True,
        architecture="gru",
        k=5,
        horizon=5,
        max_iter=1,
        online_batch_size=4,
        replay_size=64,
    )
    model = train_model(bars, config)
    assert pd.Timestamp(model.metadata["teacher_last_target_time"]) < pd.Timestamp(
        model.metadata["feedback_first_input_time"]
    )
    independent = pickle.loads(pickle.dumps(model))
    original = copy.deepcopy(model.estimator.network.state_dict())
    for i in range(18):
        result = model.predict(ctx(bars, i))
        assert "warmup" in result, result
        assert model.stats["evaluated_predictions"] == max(0, i - 8)
        assert model.stats["updates"] == max(0, i - 8) // 4
        if i < 9:
            assert result["feedback"] == [0] * 6
        if i == 9:
            assert result["feedback"][3] == pytest.approx(
                (bars.iloc[9].close / bars.iloc[4].close - 1) * 100
            )
    for i in range(18):
        assert model.predict(ctx(bars, i, "AAPL")) == independent.predict(ctx(bars, i, "AAPL"))
    for key, value in original.items():
        torch.testing.assert_close(model.estimator.network.state_dict()[key], value)
    assert any(
        not torch.equal(original[k], v)
        for k, v in model._states["NVDA"]["estimator"].network.state_dict().items()
    )
    saved = pickle.loads(pickle.dumps(model))
    assert saved._states == {} and saved.estimator.matured == 0
    checkpoint = model.checkpoint_state()
    saved_estimator = checkpoint["states"]["NVDA"]["estimator"].__getstate__()
    assert all(v.device.type == "cpu" for v in saved_estimator["weights"].values())
    assert len(saved_estimator["replay"]) == 9
    assert model.stats["runtime_device"] == "cpu"


def test_subsampled_feedback_uses_real_segment_continuity(bars, monkeypatch):
    from quant_workbench import sequence_model

    monkeypatch.setenv("QUANT_TORCH_DEVICE", "cpu")
    monkeypatch.setattr(sequence_model, "MAX_SEQUENCE_SAMPLES", 200)
    config = TimeSeriesConfig(
        enabled=True, architecture="gru", k=5, horizon=5, max_iter=1, min_training_samples=50
    )
    values, info = training_sequences(bars, config)
    assert len(info) <= 200
    assert (info.timestamp.diff().dropna() == pd.Timedelta(minutes=2)).all()
    model = train_model(bars, config)
    assert model.metadata["sampling_stride"] == 2
    assert model.metadata["feedback_nonzero_samples"] > 30


def test_subsampling_keeps_all_stocks_and_stable_selector_does_not_use_test(bars, monkeypatch):
    from quant_workbench import sequence_model
    from quant_workbench.sequence_study import stability_metrics, stable_select

    monkeypatch.setattr(sequence_model, "MAX_SEQUENCE_SAMPLES", 400)
    frame = pd.concat([bars.assign(symbol=s) for s in ("A", "B", "C", "D", "E")])
    _, info = training_sequences(frame, TimeSeriesConfig(k=5, horizon=5, min_training_samples=50))
    assert set(info.symbol) == {"A", "B", "C", "D", "E"}
    assert len(info) <= 400
    with pytest.raises(ValueError, match="4个交易日"):
        stability_metrics({"daily_returns": [{"return_pct": 1}]})
    metrics = stability_metrics(
        {
            "daily_returns": [{"return_pct": v} for v in (1, 1, -1, -1)],
            "metrics": {"max_drawdown_pct": 2},
        }
    )
    candidate = dict(
        name="unstable", status="completed", metrics={"roundtrips": 10}, test_return=100, **metrics
    )
    assert stable_select([candidate]) is None


def test_cuda_graph_reads_updated_weights_and_is_not_serialized(monkeypatch):
    import torch
    from quant_workbench.sequence_model import SequenceEstimator
    from sklearn.preprocessing import StandardScaler

    if not torch.cuda.is_available():
        pytest.skip("requires CUDA")
    monkeypatch.setenv("QUANT_TORCH_DEVICE", "cuda")
    monkeypatch.setenv("QUANT_CUDA_GRAPHS", "1")
    rng = np.random.default_rng(12)
    scalers = {
        key: StandardScaler().fit(rng.normal(size=(50, width)))
        for key, width in (("short", 7), ("long", 7), ("context", 6))
    }
    estimator = SequenceEstimator(TimeSeriesConfig(architecture="gru", k=5), scalers)
    batch = {
        "short": rng.normal(size=(1, 5, 7)).astype(np.float32),
        "long": rng.normal(size=(1, 78, 7)).astype(np.float32),
        "length": np.array([12]),
        "context": rng.normal(size=(1, 12)).astype(np.float32),
    }
    initial = estimator.predict_batch(batch)
    assert estimator._cuda_prediction is not None
    for step in range(3):
        estimator.fit_batch(batch, [step % 2], [20.0], estimator.optimizer)
        batch["context"] += 0.1
        batch["length"][:] += 3
        estimator.temperature = 0.7 + step / 10
        actual = estimator.predict_batch(batch)
        estimator._cuda_graph_enabled = False
        expected = estimator.predict_batch(batch)
        estimator._cuda_graph_enabled = True
        for left, right in zip(actual, expected, strict=True):
            np.testing.assert_allclose(left, right, rtol=1e-5, atol=1e-5)
    assert not np.array_equal(initial[0], actual[0])
    restored = pickle.loads(pickle.dumps(estimator))
    assert restored._cuda_prediction is None
    for left, right in zip(restored.predict_batch(batch), expected, strict=True):
        np.testing.assert_allclose(left, right, rtol=1e-5, atol=1e-5)


def test_cuda_training_cache_preserves_weights_and_feedback(bars, monkeypatch):
    import torch

    if not torch.cuda.is_available():
        pytest.skip("requires CUDA")
    monkeypatch.setenv("QUANT_TORCH_DEVICE", "cuda")
    config = TimeSeriesConfig(enabled=True, architecture="gru", k=5, max_iter=2)
    monkeypatch.setenv("QUANT_TRAIN_CACHE_MIB", "0")
    reference = train_model(bars, config)
    monkeypatch.setenv("QUANT_TRAIN_CACHE_MIB", "256")
    cached = train_model(bars, config)
    assert cached.metadata["feedback_nonzero_samples"] == reference.metadata[
        "feedback_nonzero_samples"
    ]
    assert cached.estimator.temperature == reference.estimator.temperature
    for name, weight in reference.estimator.network.state_dict().items():
        torch.testing.assert_close(weight, cached.estimator.network.state_dict()[name])
