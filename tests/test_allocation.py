import numpy as np
import pandas as pd
import pytest
from quant_workbench.allocation import AllocationConfig, allocate
from quant_workbench.engine import simulate
from quant_workbench.market_data import session_minutes
from quant_workbench.models import StrategyConfig
from quant_workbench.position import PositionConfig, simulate_positions


def assert_ledger(curve, initial=100000):
    for p in curve:
        assert p["cash"] >= -1e-7
        assert p["equity"] == pytest.approx(p["cash"] + sum(
            a["market_value"] for a in p["assets"].values()), abs=1e-6)
        assert p["equity"]-initial == pytest.approx(
            p["realized_pnl"]+p["unrealized_pnl"], abs=1e-6)
        assert p["cash_weight"]+sum(a["weight"] for a in p["assets"].values()) == pytest.approx(1)


def test_allocator_respects_eligibility_and_risk_caps():
    rng = np.random.default_rng(12)
    history = pd.DataFrame(rng.normal(size=(80, 3))*[.002, .02, .03], columns=list("ABC"))
    cfg = AllocationConfig(enabled=True, max_positions=2, max_weight=.5)
    weights, diagnostic = allocate(cfg, list("ABC"), history,
                                   dict(A=.3, B=.3, C=0), dict(A=0, B=0, C=0),
                                   dict(A=0, B=0, C=10), dict(A=.001, B=.001, C=.001))
    assert diagnostic["status"] == "optimized"
    assert weights["C"] == 0  # An attractive forecast cannot override a strategy rejection.
    assert weights["A"] > weights["B"]
    assert max(weights.values()) <= .5+1e-8
    assert sum(weights.values()) <= .6+1e-8


def rotation_bars():
    times = session_minutes("2024-01-02", "2024-01-04")
    minute = np.tile(np.arange(390), 2)
    frames = []
    for symbol in "ABC":
        increments = np.where(minute < 150, .0004 if symbol != "C" else -.0002,
                              -.0004 if symbol == "A" else .0005)
        close = 100*np.exp(np.cumsum(increments))
        opening = np.r_[100, close[:-1]]
        frames.append(pd.DataFrame(dict(timestamp=times, symbol=symbol, open=opening,
                                       high=np.maximum(opening, close)+.01,
                                       low=np.minimum(opening, close)-.01,
                                       close=close, volume=1000000)))
    return pd.concat(frames, ignore_index=True)


def test_shared_cash_rotation_and_future_invariance():
    frame = rotation_bars()
    cfg = StrategyConfig(strategy="sma", daily_loss_bps=1000, allocation=AllocationConfig(
        enabled=True, max_positions=2, max_weight=.5, rebalance_band=0,
        max_daily_turnover=5, rebalance_minutes=30,
    ))
    result = simulate(frame, cfg, "2024-01-02", "2024-01-04", record_market=True)
    assert_ledger(result["portfolio_curve"])
    assert any(sum(a["shares"] > 0 for a in p["assets"].values()) > 1
               for p in result["portfolio_curve"])
    assert any(t["symbol"] == "A" and t["side"] == "sell" for t in result["trades"])
    assert any(t["symbol"] == "C" and t["side"] == "buy" for t in result["trades"])
    assert all(p["position"] == 0 for p in result["positions"])
    assert sum(p["net_profit"] for p in result["contributions"]) == pytest.approx(
        result["metrics"]["net_profit"])
    changed = frame.copy()
    later = changed.timestamp >= pd.Timestamp("2024-01-03", tz="America/New_York")
    changed.loc[later, ["open", "high", "low", "close"]] *= 1.3
    other = simulate(changed, cfg, "2024-01-02", "2024-01-04", record_market=True)
    assert result["portfolio_curve"][:390] == other["portfolio_curve"][:390]
    assert [t for t in result["trades"] if t["timestamp"] < "2024-01-03"] == [
        t for t in other["trades"] if t["timestamp"] < "2024-01-03"]


def test_long_allocation_details_balance_and_future_invariance():
    from quant_workbench.market_data import demo_data

    frame = demo_data()
    cfg = PositionConfig(model="equal_weight", allocation=AllocationConfig(
        enabled=True, max_daily_turnover=.2,
    ))
    result = simulate_positions(frame, cfg, "2024-02-01", "2024-03-01")
    assert_ledger(result["curve"])
    assert result["allocation_decisions"]
    prefix = simulate_positions(frame, cfg, "2024-02-01", "2024-02-15")
    assert prefix["curve"] == [p for p in result["curve"] if p["date"] < "2024-02-15"]
    assert max(sum(w > 1e-7 for w in d["target_weights"].values())
               for d in result["allocation_decisions"]) <= 3


def test_model_veto_cannot_be_overridden_by_allocator():
    class Reject:
        audit = []
        stats = {}
        config = type("Config", (), {"horizon": 5})()

        def predict(self, request):
            return dict(allow_entry=False, expected_return_bps=100, risk_fraction=1)

    result = simulate(rotation_bars(), StrategyConfig(
        strategy="sma", allocation=AllocationConfig(enabled=True),
    ), "2024-01-02", "2024-01-04", model_filter=Reject())
    assert result["trades"] == []
    assert result["metrics"]["final_equity"] == 100000


def test_published_short_portfolio_uses_requested_stocks_and_independent_data(
    tmp_path, monkeypatch,
):
    from quant_workbench.deployments import publish
    from quant_workbench.market_data import demo_data
    from quant_workbench.models import ExperimentInput
    from quant_workbench.portfolio_export import portfolio_rows
    from quant_workbench.repository import Repository
    from quant_workbench.research import create_experiment, has_prior_exposure
    from quant_workbench.simulations import (
        SimulationInput,
        begin_simulation,
        execute_simulation,
        get_job,
        snapshot,
    )

    repo = Repository(tmp_path)
    data = repo.save_dataset(demo_data(), "demo", "synthetic", True)
    experiment = create_experiment(repo, ExperimentInput(
        dataset_id=data["id"], symbols=data["symbols"], start="2024-01-02",
        train_end="2024-01-03", validation_end="2024-01-04", end="2024-01-05",
        config=StrategyConfig(strategy="sma", allocation=AllocationConfig(enabled=True)),
        model={"enabled": False},
    ))
    with repo.connect() as db:
        db.execute("INSERT INTO runs VALUES (?, 'validation', 'completed', NULL, 0)",
                   (experiment["id"],))
    deployed = publish(repo, experiment["id"])
    assert deployed["strategy_config"]["allocation"]["enabled"]
    repo.path("datasets", data["id"], ".parquet").unlink()
    calls = []

    def fetch(request, progress=None):
        calls.append(request)
        return demo_data()[lambda f: f.symbol.isin(request.symbols)]

    monkeypatch.setattr("quant_workbench.simulations.fetch_provider", fetch)
    job = begin_simulation(repo, "workspace", SimulationInput(
        source_id=deployed["id"], symbol="AAPL", symbols=["AAPL", "AMD"],
        start="2024-01-03", end="2024-01-04",
    ))
    execute_simulation(repo, "workspace", job["id"])
    assert get_job(repo, "workspace", job["id"])["status"] == "completed"
    result = snapshot(repo, "workspace", job["id"])
    assert calls[0].symbols == ["AAPL", "AMD"]
    assert set(result["portfolio_curve"][0]["assets"]) == {"AAPL", "AMD"}
    rows = list(portfolio_rows(result["portfolio_curve"]))
    assert len(rows) == 390*2 and "asset_weight" in rows[0]
    with repo.connect() as db:
        assert has_prior_exposure(db, ["AMD"], "2024-01-03", "2024-01-04")
