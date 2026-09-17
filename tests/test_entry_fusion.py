import copy

import numpy as np
import pandas as pd
import pytest
from quant_workbench.engine import simulate
from quant_workbench.fusion import risk_overlay
from quant_workbench.market_data import session_minutes
from quant_workbench.models import StrategyConfig


def test_risk_overlay_weak_evidence_scales_and_adverse_forecast_vetoes():
    allow, fraction = risk_overlay(0.51, 2, 9)
    assert allow and 0.25 < fraction < 1
    assert risk_overlay(0.60, 12, 9)[0]
    assert risk_overlay(0.60, 12, 9)[1] == pytest.approx(1)
    assert not risk_overlay(0.4, -2, 9)[0]
    assert not risk_overlay(0.55, -10, 9)[0]
    for invalid in (None, float("nan"), float("inf")):
        assert risk_overlay(0.6, invalid, 9) == (False, 0)
    assert risk_overlay(1.5, 10, 9) == (False, 0)


def test_model_position_size_and_funnel_are_causal():
    n = len(session_minutes("2024-01-03", "2024-01-04"))
    values = [100 + i * 0.01 for i in range(n)]
    frame = pd.DataFrame(
        dict(
            timestamp=session_minutes("2024-01-03", "2024-01-04"),
            symbol="TEST",
            open=values,
            high=values,
            low=values,
            close=values,
            volume=100_000,
        )
    )

    class Model:
        audit = []
        stats = {}

        def predict(self, context):
            return {"allow_entry": True, "risk_fraction": 0.5}

    config = StrategyConfig(strategy="sma", fast=2, slow=3)
    full = simulate(frame, config, "2024-01-03", "2024-01-04")
    half = simulate(frame, config, "2024-01-03", "2024-01-04", model_filter=Model())
    assert half["trades"][0]["quantity"] == full["trades"][0]["quantity"] // 2
    assert half["trades"][0]["model_risk_fraction"] == 0.5
    assert half["decision_funnel"]["TEST"]["entry_fills"] == 1
    assert half["positions"][0]["position"] == 0
    changed = frame.copy()
    changed.loc[200:, ["open", "high", "low", "close"]] *= 2
    result = simulate(changed, config, "2024-01-03", "2024-01-04", model_filter=Model())
    assert result["trades"][0] == half["trades"][0]


def test_sequence_scaled_return_and_legacy_checkpoint_compatibility(monkeypatch):
    torch = pytest.importorskip("torch")
    from quant_workbench.sequence_model import SequenceEstimator, cpu_tree
    from quant_workbench.timeseries import TimeSeriesConfig
    from sklearn.preprocessing import StandardScaler

    monkeypatch.setenv("QUANT_TORCH_DEVICE", "cpu")
    scalers = {
        "short": StandardScaler().fit(np.zeros((2, 7))),
        "long": StandardScaler().fit(np.zeros((2, 7))),
        "context": StandardScaler().fit(np.zeros((2, 6))),
    }
    config = TimeSeriesConfig(enabled=True, architecture="gru", return_normalization=True)
    estimator = SequenceEstimator(config, scalers, return_scale=20)
    sample = {
        "short": np.zeros((1, 5, 7)),
        "long": np.zeros((1, 3, 7)),
        "length": np.array([3]),
        "context": np.zeros((1, 12)),
    }
    with torch.no_grad():
        for weight in estimator.network.parameters():
            weight.zero_()
        estimator.network.regressor.bias.fill_(0.5)
    p, bps = estimator.predict_batch(sample)
    assert p[0] == pytest.approx(0.5) and bps[0] == pytest.approx(10)
    saved = estimator.__getstate__()
    restored = copy.deepcopy(estimator)
    assert restored.return_scale == 20
    np.testing.assert_allclose(restored.predict_batch(sample)[1], bps)
    # Old checkpoints have no scale or new config fields; they keep 100 bps units
    # and restore under current defaults (adaptive gate, normalized returns).
    saved.pop("return_scale")
    saved["config"].__dict__.pop("return_normalization", None)
    saved["config"].__dict__.pop("decision_mode", None)
    restored.__setstate__(saved)
    assert restored.return_scale == 100
    assert restored.config.return_normalization is True
    assert restored.config.decision_mode == "adaptive"
    restored.fit_batch(sample, [1], [12], restored.optimizer)
    assert all(torch.isfinite(v).all() for v in cpu_tree(restored.network.state_dict()).values())


def test_full_confidence_scaled_entry_rechecks_cost_after_open_gap(monkeypatch):
    from types import SimpleNamespace

    import quant_workbench.engine as engine

    class Rule:
        def __init__(self, *args):
            self.max_quantity = 100
            self.pending_take = 0.2
            self.entry_diagnostic = "test"

        def reset(self, cash):
            pass

        def observe(self, *args):
            return True, None

        def filled(self, *args):
            pass

    class Filter:
        config = SimpleNamespace(decision_mode="risk_scaled")
        audit = []
        stats = {}

        def predict(self, ctx):
            return {"allow_entry": True, "risk_fraction": 1.0}

    monkeypatch.setattr(engine, "IntradayRules", Rule)
    times = session_minutes("2024-01-03", "2024-01-04")
    prices = [100] + [1000] * (len(times) - 1)
    frame = pd.DataFrame(
        dict(
            timestamp=times,
            symbol="TEST",
            open=prices,
            high=prices,
            low=prices,
            close=prices,
            volume=100_000,
        )
    )
    result = simulate(
        frame,
        StrategyConfig(strategy="adaptive_intraday"),
        "2024-01-03",
        "2024-01-04",
        model_filter=Filter(),
    )
    assert not result["trades"]
    assert result["decision_funnel"]["TEST"]["unfilled_entry_attempts"] > 0


def test_risk_scaled_model_preserves_warmup_and_strict_mode(monkeypatch):
    from quant_workbench.market_data import demo_data
    from quant_workbench.timeseries import TimeSeriesConfig, train_model

    frame = demo_data().query("symbol == 'NVDA'")
    frame = frame[frame.timestamp < "2024-01-05"].reset_index(drop=True)
    base = train_model(
        frame,
        TimeSeriesConfig(
            enabled=True, k=5, max_iter=1, decision_mode="risk_scaled", cost_aware=True
        ),
    )
    strict = copy.deepcopy(base)
    strict.config = strict.config.model_copy(update={"decision_mode": "strict"})
    for model in (base, strict):
        monkeypatch.setattr(model, "_predict_heads", lambda *args: (0.51, 2.0))
    for index in range(11):
        bar = frame.iloc[index].to_dict()
        context = {
            "symbol": "NVDA",
            "timestamp": bar["timestamp"].isoformat(),
            "recent_bars": [bar],
            "round_trip_cost_bps": 9.0,
        }
        scaled = base.predict(context)
        hard = strict.predict(context)
        if index < 10:
            assert not scaled["allow_entry"] and scaled["risk_fraction"] == 0
        else:
            assert scaled["allow_entry"] and 0 < scaled["risk_fraction"] < 1
        assert not hard["allow_entry"]


def test_quantile_threshold_requires_samples_and_floors_at_half():
    from quant_workbench.fusion import quantile_threshold

    assert quantile_threshold([]) is None
    assert quantile_threshold([0.5] * 49) is None
    # Concentrated calibrated probabilities cannot be blocked by a fixed 0.55-style bar.
    tight = [0.49 + 0.01 * (i % 3) for i in range(200)]
    assert quantile_threshold(tight) == pytest.approx(0.51)
    spread = [0.3 + 0.004 * i for i in range(200)]
    assert quantile_threshold(spread) == pytest.approx(np.quantile(spread, 0.8))
    assert quantile_threshold(spread, quantile=0.95) > quantile_threshold(spread, quantile=0.5)


def test_adaptive_mode_gates_on_rolling_quantile_and_scales_size(monkeypatch):
    from quant_workbench.market_data import demo_data
    from quant_workbench.timeseries import TimeSeriesConfig, train_model

    frame = demo_data().query("symbol == 'NVDA'")
    frame = frame[frame.timestamp < "2024-01-05"].reset_index(drop=True)
    model = train_model(
        frame,
        TimeSeriesConfig(enabled=True, k=5, max_iter=1, decision_mode="adaptive", cost_aware=True),
    )
    calls = {"probability": []}

    def fake_heads(state, features):
        # Warmup ends after 2k=10 bars; history then fills with 0.50 readings.
        return (0.52 if len(calls["probability"]) >= 60 else 0.5), 6.0

    monkeypatch.setattr(model, "_predict_heads", fake_heads)
    allowed = None
    for index in range(80):
        bar = frame.iloc[index].to_dict()
        context = {
            "symbol": "NVDA",
            "timestamp": bar["timestamp"].isoformat(),
            "recent_bars": [bar],
            "round_trip_cost_bps": 5.0,
        }
        decision = model.predict(context)
        calls["probability"].append(decision.get("probability"))
        if index < 10:
            assert not decision["allow_entry"] and decision["risk_fraction"] == 0
        if decision.get("adaptive_threshold") is not None:
            assert decision["adaptive_threshold"] <= 0.52
        if decision["allow_entry"]:
            allowed = decision
    assert allowed is not None
    assert 0 < allowed["risk_fraction"] < 1


def test_adaptive_mode_blocks_below_quantile(monkeypatch):
    from quant_workbench.market_data import demo_data
    from quant_workbench.timeseries import TimeSeriesConfig, train_model

    frame = demo_data().query("symbol == 'NVDA'")
    frame = frame[frame.timestamp < "2024-01-05"].reset_index(drop=True)
    model = train_model(
        frame, TimeSeriesConfig(enabled=True, k=5, max_iter=1, decision_mode="adaptive")
    )
    index = {"i": 0}

    def fake_heads(state, features):
        index["i"] += 1
        # Fill history with 0.9 readings, then predict 0.6: above the 0.5 floor but
        # far below the rolling 80th percentile, so the adaptive gate must veto.
        return (0.6 if index["i"] > 60 else 0.9), 6.0

    monkeypatch.setattr(model, "_predict_heads", fake_heads)
    decision = None
    for i in range(70):
        bar = frame.iloc[i].to_dict()
        decision = model.predict(
            {
                "symbol": "NVDA",
                "timestamp": bar["timestamp"].isoformat(),
                "recent_bars": [bar],
                "round_trip_cost_bps": 5.0,
            }
        )
    assert decision is not None
    assert decision["adaptive_threshold"] == pytest.approx(0.9)
    assert not decision["allow_entry"]
    assert decision["risk_fraction"] == 0
    assert "分位" in decision["reason"]


def test_gru_temperature_calibration_and_device_policy(monkeypatch):
    torch = pytest.importorskip("torch")
    from quant_workbench.sequence_model import (
        SequenceEstimator,
        _best_temperature,
        select_device,
    )
    from quant_workbench.timeseries import TimeSeriesConfig
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(11)
    labels = rng.integers(0, 2, 4000)
    logits = rng.normal(2.5, 1.0, 4000)  # overconfident, no signal
    temperature = _best_temperature(labels, logits)
    assert temperature > 1.5  # must flatten towards calibrated probabilities
    assert _best_temperature(labels, np.zeros(4000)) == pytest.approx(1.0, abs=0.2)

    monkeypatch.setenv("QUANT_TORCH_DEVICE", "cpu")
    assert select_device() == "cpu"
    monkeypatch.setenv("QUANT_TORCH_DEVICE", "mps")
    with pytest.raises(ValueError, match="MPS"):
        select_device()
    monkeypatch.setenv("QUANT_TORCH_DEVICE", "cpu")

    scalers = {
        "short": StandardScaler().fit(np.zeros((2, 7))),
        "long": StandardScaler().fit(np.zeros((2, 7))),
        "context": StandardScaler().fit(np.zeros((2, 6))),
    }
    estimator = SequenceEstimator(
        TimeSeriesConfig(enabled=True, architecture="gru"), scalers, return_scale=100
    )
    assert estimator.temperature == 1.0
    sample = {
        "short": np.zeros((1, 5, 7)),
        "long": np.zeros((1, 3, 7)),
        "length": np.array([3]),
        "context": np.zeros((1, 12)),
    }
    with torch.no_grad():
        for weight in estimator.network.parameters():
            weight.zero_()
        estimator.network.classifier.bias.fill_(4.0)
    hot = estimator.predict_batch(sample)[0][0]
    estimator.temperature = 4.0
    cool = estimator.predict_batch(sample)[0][0]
    assert hot > 0.9 and cool < hot  # higher temperature pulls toward 0.5


def test_adaptive_local_range_does_not_assume_session_vwap_is_reachable():
    from types import SimpleNamespace

    from quant_workbench.strategies import IntradayRules

    cfg = StrategyConfig(
        strategy="adaptive_intraday",
        regime_window=30,
        slow=21,
        fast=8,
        reversion_bps=10,
        reversion_atr=1,
    )
    rules = IntradayRules(cfg, "adaptive_intraday")
    prices = np.r_[np.full(28, 100.0), 99.5, 99.4, 99.5]
    bars = [
        SimpleNamespace(open=p - 0.01, close=p, high=p + 0.02, low=p - 0.02, volume=1000)
        for p in prices
    ]
    # A high session VWAP alone cannot manufacture a mean-reversion opportunity.
    down = np.linspace(110, 100, 31)
    falling = [
        SimpleNamespace(open=p - 0.01, close=p, high=p + 0.02, low=p - 0.02, volume=1000)
        for p in down
    ]
    assert not rules.regime_signal(falling, down, 0.2, 110)[0]
    signal, distance, mode = rules.regime_signal(bars, prices, 0.4, 110)
    assert mode == "local_range"
    assert distance < 1  # Local target near 100, not the unreachable session VWAP 110.
