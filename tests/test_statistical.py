import numpy as np
import pandas as pd
import pytest
from quant_workbench.models import StrategyConfig
from quant_workbench.statistical import StatisticalForecast


@pytest.mark.parametrize("strategy", ["ou_reversion", "kalman_trend"])
def test_statistical_forecasts_depend_only_on_observed_prefix(strategy):
    cfg = StrategyConfig(stat_window=60)
    rng = np.random.default_rng(9)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 150)))
    one, two = StatisticalForecast(cfg, strategy), StatisticalForecast(cfg, strategy)
    for i, price in enumerate(prices[:100]):
        one.observe(price)
        two.observe(price)
        assert one.forecast() == two.forecast()
        if i < 60:
            assert one.forecast() is None
    recorded = one.forecast()
    for price in prices[100:] * 2:
        two.observe(price)
    assert one.forecast() == recorded


def test_kalman_trend_and_ou_uncertainty_are_finite():
    cfg = StrategyConfig(stat_window=60)
    trend = StatisticalForecast(cfg, "kalman_trend")
    for price in 100 * np.exp(np.arange(140) * 2 / 10000):
        trend.observe(price)
    result = trend.forecast()
    assert result["mean_bps"] == pytest.approx(30, abs=0.1)
    assert result["uncertainty_bps"] > 0
    assert np.linalg.eigvalsh(trend.covariance).min() >= 0
    rng = np.random.default_rng(5)
    ou = StatisticalForecast(cfg, "ou_reversion")
    x = 0
    for _ in range(140):
        x = 0.9 * x + rng.normal(0, 5)
        ou.observe(100 * np.exp(x / 10000))
    assert ou.forecast()["half_life"] > 0
    assert np.isfinite(ou.forecast()["uncertainty_bps"])


def test_regime_gate_can_warm_start_from_pre_evaluation_history():
    from quant_workbench.strategies import basket_regime_gate

    dates = pd.bdate_range("2024-01-02", periods=7, tz="UTC")
    frame = pd.DataFrame(dict(timestamp=dates, symbol="A", close=100 * 1.01 ** np.arange(7)))
    cfg = StrategyConfig(regime_gate="drift", regime_window_days=5, regime_min_drift_bps=50)
    assert list(basket_regime_gate(frame, cfg).values()) == [False] * 6 + [True]


def test_bayesian_session_predicts_at_opening_cutoff_without_future_prices():
    from quant_workbench.market_data import session_minutes
    from quant_workbench.statistical import bayesian_session_forecasts

    times = session_minutes("2024-01-02", "2024-01-19")
    rng = np.random.default_rng(42)
    frames = []
    for symbol in ("A", "B", "C", "D", "E"):
        price = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, len(times))))
        frames.append(pd.DataFrame(dict(
            symbol=symbol, timestamp=times, open=price, high=price + 0.1,
            low=price - 0.1, close=price, volume=10000,
        )))
    frame = pd.concat(frames, ignore_index=True)
    cutoff = pd.Timestamp("2024-01-18T15:00Z")  # 10:00 NY: opening 30 bars available.
    config = StrategyConfig(strategy="bayesian_session")
    full = bayesian_session_forecasts(frame, config)
    prefix = bayesian_session_forecasts(frame[frame.timestamp <= cutoff], config)
    assert prefix
    for key, value in prefix.items():
        assert value == full[key]
        assert value["last_training_day"] < key[1]
    assert all((s, "2024-01-18") in prefix for s in ("A", "B", "C", "D", "E"))


def test_rejecting_an_add_does_not_liquidate_existing_staged_position():
    from quant_workbench.engine import simulate
    from quant_workbench.market_data import session_minutes

    times = session_minutes("2024-01-03", "2024-01-04")
    price = np.where(np.arange(len(times)) < 25, 100.0, 97.0)
    frame = pd.DataFrame(dict(timestamp=times, symbol="TEST", open=price,
                              high=price+0.6, low=price-0.6, close=price, volume=100000))

    class Filter:
        audit = []
        stats = {}

        def predict(self, context):
            return {"allow_entry": pd.Timestamp(context["timestamp"]) < times[40]}

    result = simulate(frame, StrategyConfig(
        strategy="scaled_reversion", reversion_bps=30, reversion_atr=0.5,
        max_hold_minutes=120, max_scaling_lots=3, max_daily_entries=3,
    ), "2024-01-03", "2024-01-04", model_filter=Filter(), record_market=True)
    assert any(t["side"] == "buy" for t in result["trades"])
    assert result["market_curve"][60]["shares"] > 0
