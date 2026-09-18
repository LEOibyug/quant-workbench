import numpy as np
import pandas as pd
import pytest
from quant_workbench.daily_strategies import MODELS, rule_forecasts
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig, simulate_positions


def sample():
    rng = np.random.default_rng(20260918)
    days = schedule("2024-01-02", "2024-08-01").index.strftime("%Y-%m-%d")
    frames = []
    for symbol in "ABCDEFGH":
        close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.014, len(days))))
        opening = np.r_[close[0], close[:-1]]
        frames.append(
            pd.DataFrame(
                dict(
                    day=days,
                    symbol=symbol,
                    open=opening,
                    high=np.maximum(opening, close) * 1.001,
                    low=np.minimum(opening, close) * 0.999,
                    close=close,
                    volume=10000000,
                )
            )
        )
    return pd.concat(frames, ignore_index=True)


@pytest.mark.parametrize("method", sorted(MODELS))
@pytest.mark.parametrize("policy", ["legacy", "cost_aware"])
def test_rule_causality_permutation_limits_and_ledger(method, policy):
    if method == "generated_policy":
        from quant_workbench.generated_policy import ARTIFACT
        if not ARTIFACT.exists():
            pytest.skip("Run train_generated_policy.py to validate trained artifact")
    if method == "pattern_policy":
        from quant_workbench.conditional_policy import ARTIFACT
        if not ARTIFACT.exists():
            pytest.skip("Run train_pattern_policy.py to validate trained artifact")
    frame = sample()
    cfg = PositionConfig(model=method, tranche_weight=0.1, portfolio_policy=policy)
    forecast = rule_forecasts(frame, cfg)
    cutoff = "2024-07-15" if method == "adaptive_specialist" else "2024-06-01"
    prefix = rule_forecasts(frame[frame.day < cutoff], cfg)
    assert prefix
    assert prefix == {k: v for k, v in forecast.items() if k[0] < cutoff}
    assert forecast == rule_forecasts(frame.sample(frac=1, random_state=3), cfg)
    grouped = {}
    for (day, _symbol), f in forecast.items():
        assert 0 <= f["target_weight"] <= 0.2 + 1e-8
        grouped[day] = grouped.get(day, 0) + f["target_weight"]
    assert max(grouped.values()) <= 0.95 + 1e-8
    result = simulate_positions(frame, cfg, "2024-04-03", "2024-08-01", daily_bars=True)
    for p in result["curve"]:
        assert p["cash"] >= -1e-7
        assert p["equity"] == pytest.approx(
            p["cash"] + sum(a["market_value"] for a in p["assets"].values())
        )
        assert p["equity"] - 100000 == pytest.approx(
            p["realized_pnl"] + p["unrealized_pnl"], abs=1e-6
        )
    shorter = simulate_positions(frame, cfg, "2024-04-03", cutoff, daily_bars=True)
    assert shorter["curve"] == [p for p in result["curve"] if p["date"] < cutoff]


def test_cost_aware_allocator_respects_signal_and_risk_budget():
    from quant_workbench.daily_strategies import cost_aware_targets
    from sklearn.covariance import LedoitWolf

    rng = np.random.default_rng(31)
    returns = pd.DataFrame(rng.normal(0, 0.02, (80, 3)), columns=list("ABC"))
    target = {"A": 0.2, "B": 0.1, "C": 0.0}
    old = {"A": 0.18, "B": 0.12, "C": 0.05}
    w, diagnostic = cost_aware_targets(
        list("ABC"), returns, target, old, dict.fromkeys("ABC", 0.001), 0.2, 5
    )
    assert diagnostic["status"] == "optimized"
    assert w["C"] == 0 and sum(w.values()) <= 0.3 + 1e-8
    cov = LedoitWolf().fit(returns.tail(63)).covariance_ + np.eye(3) * 1e-12
    a = np.array(list(w.values()))
    t = np.array(list(target.values()))
    assert a @ cov @ a <= t @ cov @ t + 1e-9
    assert (
        sum(abs(w[s] - old[s]) for s in "ABC") <= sum(abs(target[s] - old[s]) for s in "ABC") + 1e-8
    )


def test_shared_execution_is_order_invariant_and_budgets_buys():
    from quant_workbench.allocation import AllocationConfig

    frame = sample()
    cfg = PositionConfig(
        model="cross_momentum",
        portfolio_policy="cost_aware",
        tranche_weight=0.1,
        allocation=AllocationConfig(enabled=False, max_daily_turnover=0.2),
        entry_band=0.005,
    )
    result = simulate_positions(frame, cfg, "2024-04-03", "2024-08-01", daily_bars=True)
    reordered = simulate_positions(
        frame.sample(frac=1, random_state=22), cfg, "2024-04-03", "2024-08-01", daily_bars=True
    )
    assert result["trades"] == reordered["trades"]
    assert result["curve"] == reordered["curve"]
    by_day = {day: g.set_index("symbol") for day, g in frame.groupby("day")}
    for previous, point in zip(result["curve"][:-1], result["curve"][1:], strict=True):
        day = point["date"]
        opening = previous["cash"] + sum(
            a["shares"] * by_day[day].loc[s, "open"] for s, a in previous["assets"].items()
        )
        regular = sum(
            t["quantity"] * t["price"]
            for t in result["trades"]
            if t["date"] == day and t["reason"] != "risk_exit"
        )
        assert regular <= opening * 0.2 + 1e-6


def test_generated_policy_rejects_changed_frozen_artifact(monkeypatch):
    monkeypatch.setattr('quant_workbench.generated_policy.artifact_digest', lambda: 'b'*64)
    with pytest.raises(ValueError, match='冻结版本'):
        simulate_positions(sample(), PositionConfig(model='generated_policy',classifier_sha256='a'*64),
                           '2024-04-03','2024-08-01',daily_bars=True)
