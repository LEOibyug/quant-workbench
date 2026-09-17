import asyncio
import json

import httpx
import pandas as pd
import pytest
from quant_workbench.api import app
from quant_workbench.deployments import publish
from quant_workbench.engine import simulate
from quant_workbench.market_data import demo_data, session_minutes
from quant_workbench.models import ExperimentInput, StrategyConfig
from quant_workbench.repository import Repository
from quant_workbench.research import begin_run, create_experiment
from quant_workbench.simulations import (
    SimulationInput,
    begin_simulation,
    execute_simulation,
    get_job,
    snapshot,
)


@pytest.fixture
def research(tmp_path):
    repo = Repository(tmp_path)
    frame = demo_data()
    frame = frame[frame.symbol == "NVDA"]
    ds = repo.save_dataset(frame, "demo", "synthetic", True)
    exp = create_experiment(
        repo,
        ExperimentInput(
            dataset_id=ds["id"],
            symbols=["NVDA"],
            start="2024-01-02",
            train_end="2024-01-03",
            validation_end="2024-01-04",
            end="2024-01-05",
            config={"strategy": "sma", "fast": 2, "slow": 5},
            model={"enabled": True, "k": 5, "max_iter": 1},
        ),
    )
    return repo, exp


def request(exp, **kwargs):
    return SimulationInput(
        **dict(
            dict(source_id=exp["id"], symbol="NVDA", start="2024-01-03", end="2024-01-04"), **kwargs
        )
    )


def validate(repo, exp):
    with repo.connect() as db:
        db.execute("INSERT INTO runs VALUES (?, 'validation', 'completed', NULL, 0)", (exp["id"],))


def test_trace_partial_exit_accounting_and_observed_prefixes():
    values = [99, 100, 101, 95, 101, 102] + [103 + i * 0.01 for i in range(384)]
    frame = pd.DataFrame(
        {
            "timestamp": session_minutes("2024-01-03", "2024-01-04"),
            "symbol": "TEST",
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": 100_000,
        }
    )
    frame.loc[3, ["open", "high"]] = 101
    frame.loc[3:8, "volume"] = 1000
    seen = []

    def progress(done, total, points, trades):
        assert done == len(points) <= total
        assert all(t["timestamp"] <= points[-1]["timestamp"] for t in trades)
        seen.append(json.loads(json.dumps(points)))

    result = simulate(
        frame,
        StrategyConfig(fast=2, slow=3),
        "2024-01-03",
        "2024-01-04",
        record_market=True,
        progress=progress,
    )
    assert 1 < len(seen) < 390
    for prefix in seen:
        assert prefix == result["market_curve"][: len(prefix)]
    first_sells = [
        t for t in result["trades"] if t["position_id"] == "TEST-1" and t["side"] == "sell"
    ]
    assert len(first_sells) > 1
    assert sum(t["realized_pnl"] or 0 for t in result["trades"]) == pytest.approx(
        result["metrics"]["net_profit"]
    )
    for point in result["market_curve"]:
        assert point["cash"] + point["shares"] * point["close"] == pytest.approx(point["equity"])
        assert point["realized_pnl"] + point["unrealized_pnl"] == pytest.approx(
            point["equity"] - 100_000
        )
    final = result["market_curve"][-1]
    assert final["fees"] == pytest.approx(result["metrics"]["fees"])
    assert final["impact_cost"] == pytest.approx(result["metrics"]["impact_cost"])
    assert final["unrealized_pnl"] == 0
    assert result["trades"][0]["realized_pnl"] is None


def test_phase_gate_and_test_simulation_counts_as_exposure(research):
    repo, exp = research
    with pytest.raises(ValueError, match="区间"):
        begin_simulation(repo, "research", request(exp, start="2024-01-02"))
    with pytest.raises(ValueError, match="验证"):
        begin_simulation(
            repo, "research", request(exp, phase="test", start="2024-01-04", end="2024-01-05")
        )
    validate(repo, exp)
    job = begin_simulation(
        repo, "research", request(exp, phase="test", start="2024-01-04", end="2024-01-05")
    )
    # Even interrupted runs mark the test region as exposed.
    repo.recover()
    assert get_job(repo, "research", job["id"])["status"] == "failed"
    assert begin_run(repo, exp["id"], "train")["prior_test_exposure"]


def test_workspace_downloads_independent_data_without_research(research, monkeypatch):
    repo, exp = research
    validate(repo, exp)
    deployment = publish(repo, exp["id"])
    frame = repo.load_dataset(exp["dataset_id"])
    repo.path("datasets", exp["dataset_id"], ".parquet").unlink()
    repo.path("models", exp["id"], ".joblib").unlink()
    with repo.connect() as db:
        db.execute("DELETE FROM experiments")
        db.execute("DELETE FROM datasets")
    calls = []

    def fetch(params, progress=None):
        calls.append(params)
        return frame

    monkeypatch.setattr("quant_workbench.simulations.fetch_provider", fetch)
    job = begin_simulation(repo, "workspace", request(deployment))
    execute_simulation(repo, "workspace", job["id"])
    finished = get_job(repo, "workspace", job["id"])
    assert finished["status"] == "completed", finished
    assert calls[0].symbols == ["NVDA"]
    assert str(calls[0].start) < job["start"]
    assert Repository(repo.root / "workspace").list_records("datasets")
    result = snapshot(repo, "workspace", job["id"])
    assert len(result["market_curve"]) == 390
    assert exp["id"] not in json.dumps([finished, result])
    assert exp["dataset_id"] not in json.dumps([finished, result])
    with pytest.raises(KeyError):
        snapshot(repo, "research", job["id"])
    # Model boundary remains enforceable even after deleting research.
    with pytest.raises(ValueError, match="仅允许"):
        begin_simulation(repo, "workspace", request(deployment, start="2024-01-02"))
    again = begin_simulation(repo, "workspace", request(deployment))
    execute_simulation(repo, "workspace", again["id"])
    assert len(calls) == 1
    assert snapshot(repo, "workspace", again["id"])["market_curve"] == result["market_curve"]


def test_api_simulation_lifecycle_exports_and_scope(research, monkeypatch):
    repo, exp = research
    monkeypatch.setenv("QUANT_DATA_DIR", str(repo.root))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/research/simulations", json=request(exp).model_dump(mode="json")
            )
            assert response.status_code == 200
            identifier = response.json()["id"]
            path = f"/api/research/simulations/{identifier}"
            job = (await client.get(path)).json()
            assert job["status"] == "completed", job
            result = (await client.get(path + "/result")).json()
            assert len(result["market_curve"]) == job["total_bars"] == 390
            assert (await client.get(path + "/export/market_curve")).text.count("\n") == 391
            assert (
                await client.get(path.replace("research", "workspace") + "/result")
            ).status_code == 404
            assert (
                await client.get(path.replace("research", "workspace") + "/export/trades")
            ).status_code == 404
            history = (await client.get(f"/api/workspace/simulations?source_id={exp['id']}")).json()
            assert history == []
            bad = request(exp).model_dump(mode="json") | {"initial_cash": -1}
            assert (await client.post("/api/research/simulations", json=bad)).status_code == 422

    asyncio.run(run())


def test_failed_download_has_no_fabricated_result(research, monkeypatch):
    repo, exp = research
    validate(repo, exp)
    dep = publish(repo, exp["id"])

    def fail(_, progress=None):
        raise RuntimeError("private transport details must not leak")

    monkeypatch.setattr("quant_workbench.simulations.fetch_provider", fail)
    job = begin_simulation(repo, "workspace", request(dep))
    execute_simulation(repo, "workspace", job["id"])
    finished = get_job(repo, "workspace", job["id"])
    assert finished["status"] == "failed"
    assert "private" not in finished["error"]
    assert snapshot(repo, "workspace", job["id"])["market_curve"] == []


def test_simulation_exposure_warning_and_bounded_admission(research):
    repo, exp = research
    validate(repo, exp)
    with repo.connect() as db:
        db.execute("INSERT INTO runs VALUES (?, 'test', 'failed', NULL, 1)", (exp["id"],))
    # Validation of a different frozen experiment overlaps a previously seen test interval.
    other = {**exp, "id": "a" * 32, "train_end": "2024-01-04", "validation_end": "2024-01-05"}
    repo.save_experiment(other)
    job = begin_simulation(repo, "research", request(other, start="2024-01-04", end="2024-01-05"))
    assert job["prior_test_exposure"] is True
    assert any("已暴露" in w for w in job["warnings"])
    with pytest.raises(ValueError, match="正在运行"):
        begin_simulation(repo, "research", request(exp))
    repo.recover()
    # Prior workspace simulation exposure is recorded without reading research from workspace.
    dep = publish(repo, exp["id"])
    begin_simulation(repo, "workspace", request(dep))
    repo.recover()
    research_job = begin_simulation(repo, "research", request(exp))
    assert research_job["prior_test_exposure"] is True
