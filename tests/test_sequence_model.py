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


def test_device_selection_and_causal_network_masks_padding(monkeypatch):
    import torch

    monkeypatch.setenv("QUANT_TORCH_DEVICE", "auto")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert select_device() == "cuda"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert select_device() == "mps"
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    assert select_device() == "cpu"
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
