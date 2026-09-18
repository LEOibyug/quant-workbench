import asyncio
import json

import httpx
import numpy as np
import pandas as pd
import pytest
from quant_workbench.api import app
from quant_workbench.market_data import session_minutes
from quant_workbench.position import PositionConfig, daily_forecasts, simulate_positions
from quant_workbench.repository import Repository


@pytest.fixture
def bars():
    times = session_minutes("2024-01-02", "2024-01-10")
    price = np.full(len(times), 100.0)
    return pd.DataFrame(dict(
        timestamp=times, symbol="TEST", open=price, high=price + 0.1,
        low=price - 0.1, close=price, volume=100_000,
    ))


def test_multiday_bayesian_labels_mature_before_forecast():
    rng = np.random.default_rng(8)
    days = pd.bdate_range("2024-01-02", periods=60).strftime("%Y-%m-%d")
    frames = []
    for symbol in ("A", "B", "C", "D", "E"):
        price = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
        frames.append(pd.DataFrame(dict(day=days, symbol=symbol, open=price, close=price)))
    daily = pd.concat(frames)
    cfg = PositionConfig(model="bayesian", lookback=20, horizon=5)
    full = daily_forecasts(daily, cfg)
    prefix = daily_forecasts(daily[daily.day <= days[49]], cfg)
    assert prefix
    for key, value in prefix.items():
        assert value == full[key]
        assert value["last_training_target"] <= key[0]


def test_staged_positions_hold_overnight_and_conserve_capital(bars):
    cfg = PositionConfig(model="equal_weight", max_weight=0.5, tranche_weight=0.05)
    result = simulate_positions(bars, cfg, "2024-01-02", "2024-01-10")
    assert result["positions"]["TEST"] > 0
    assert result["trades"][0]["date"] > result["trades"][0]["signal_date"]
    assert len([t for t in result["trades"] if t["side"] == "buy"]) > 1
    assert all(t["quantity"] <= 50 for t in result["trades"])
    assert all(r["cash"] >= 0 and 0 <= r["gross_exposure"] <= 1 for r in result["curve"])
    assert sum(r["net_profit"] for r in result["contributions"]) == pytest.approx(
        result["metrics"]["final_equity"] - cfg.costs.initial_cash,
    )
    assert result["curve"][2]["positions"]["TEST"] > result["curve"][1]["positions"]["TEST"]


def test_hard_exit_overrides_tranche_limit(bars):
    day = bars.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    shocked = day >= "2024-01-05"
    bars.loc[shocked, ["open", "high", "low", "close"]] *= 0.75
    result = simulate_positions(
        bars, PositionConfig(model="equal_weight", max_weight=0.5, max_drawdown_pct=2),
        "2024-01-02", "2024-01-10",
    )
    exits = [t for t in result["trades"] if t["reason"] == "risk_exit"]
    assert exits and exits[0]["side"] == "sell" and exits[0]["quantity"] > 60
    assert result["metrics"]["halted"] is True
    json.dumps(result)


def test_position_job_progress_result_and_export(bars, tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DATA_DIR", str(tmp_path))
    dataset = Repository().save_dataset(bars, "synthetic", "test", True)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            response = await client.post("/api/position/run", json=dict(
                dataset_id=dataset["id"], symbols=["TEST"], start="2024-01-02", end="2024-01-10",
                config=dict(model="equal_weight"),
            ))
            assert response.status_code == 200, response.text
            identifier = response.json()["id"]
            job = (await client.get(f"/api/research/operations/{identifier}")).json()
            assert job["status"] == "completed", job
            assert job["result"]["positions"]["TEST"] > 0
            export = await client.get(f"/api/position/{identifier}/export")
            assert export.status_code == 200 and "staged_rebalance" in export.text
            from quant_workbench.research import has_prior_exposure

            with Repository().connect() as db:
                assert has_prior_exposure(db, ["TEST"], "2024-01-05", "2024-01-10")
                assert not has_prior_exposure(db, ["OTHER"], "2024-01-05", "2024-01-10")

    asyncio.run(run())
