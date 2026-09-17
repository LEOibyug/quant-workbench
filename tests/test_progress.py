import asyncio

import httpx
import pandas as pd
import pytest
from quant_workbench.api import app
from quant_workbench.engine import simulate
from quant_workbench.market_data import demo_data, session_minutes
from quant_workbench.models import ExperimentInput, StrategyConfig
from quant_workbench.operations import begin_operation, execute_operation, get_operation
from quant_workbench.repository import Repository
from quant_workbench.research import begin_run, execute_run


def test_bounded_operations_progress_and_recovery(tmp_path, monkeypatch):
    repo = Repository(tmp_path)
    job = begin_operation(repo, "download")
    with pytest.raises(ValueError, match="仍在执行"):
        begin_operation(repo, "download")
    seen = []

    def fetch(request, progress):
        progress("下载第1页", 100, None, "条")
        seen.append(get_operation(repo, job["id"]))
        return demo_data().query("symbol == 'NVDA'")

    monkeypatch.setattr("quant_workbench.operations.fetch_provider", fetch)
    from quant_workbench.models import ProviderInput

    execute_operation(
        repo, job, ProviderInput(symbols=["NVDA"], start="2024-01-02", end="2024-01-03")
    )
    assert seen[0]["done"] == 100 and seen[0]["total"] is None
    assert seen[0]["status"] == "running"
    result = get_operation(repo, job["id"])
    assert result["status"] == "completed"
    assert result["result"]["rows"] > 0
    interrupted = begin_operation(repo, "train")
    repo.recover()
    assert get_operation(repo, interrupted["id"])["status"] == "failed"


def test_training_and_phase_progress_over_api(tmp_path, monkeypatch):
    repo = Repository(tmp_path)
    monkeypatch.setenv("QUANT_DATA_DIR", str(tmp_path))
    ds = repo.save_dataset(demo_data().query("symbol == 'NVDA'"), "demo", "synthetic", True)
    request = ExperimentInput(
        dataset_id=ds["id"],
        symbols=["NVDA"],
        start="2024-01-02",
        train_end="2024-01-03",
        validation_end="2024-01-04",
        end="2024-01-05",
        model={"enabled": True, "architecture": "linear", "k": 5, "max_iter": 1},
    )
    seen = []
    from quant_workbench.operations import save_operation

    def save(repo, job):
        seen.append((job["stage"], job["done"], job["total"]))
        save_operation(repo, job)

    monkeypatch.setattr("quant_workbench.operations.save_operation", save)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/research/operations/train", json=request.model_dump(mode="json")
            )
            assert response.status_code == 200
            result = (await client.get("/api/research/operations/" + response.json()["id"])).json()
            assert result["status"] == "completed", result
            assert any(total and 0 < done <= total for _, done, total in seen)
            identifier = result["result"]["id"]
            begin_run(repo, identifier, "validation")
            execute_run(repo, identifier, "validation")
            run = repo.runs(identifier)[0]
            assert run["status"] == "completed"
            assert run["progress"]["stage"] == "运行完成"
            assert run["progress"]["finished_at"] >= run["progress"]["started_at"]

    asyncio.run(check())


def test_failed_operation_sanitizes_unexpected_errors(tmp_path, monkeypatch):
    repo = Repository(tmp_path)
    job = begin_operation(repo, "download")

    def fetch(*args, **kwargs):
        raise RuntimeError("sensitive transport error")

    monkeypatch.setattr("quant_workbench.operations.fetch_provider", fetch)
    execute_operation(repo, job, None)
    stored = get_operation(repo, job["id"])
    assert stored["status"] == "failed"
    assert "sensitive" not in stored["error"]


def test_multistock_progress_without_recording_and_diagnostics():
    times = session_minutes("2024-01-03", "2024-01-04")
    prices = [100 + i * 0.01 for i in range(len(times))]
    frame = pd.DataFrame(
        {
            "timestamp": times,
            "symbol": "ONE",
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": 100_000,
        }
    )
    events = []
    simulate(
        pd.concat([frame, frame.assign(symbol="TWO")]),
        StrategyConfig(fast=2, slow=3),
        "2024-01-03",
        "2024-01-04",
        progress=lambda done, total, *_: events.append((done, total)),
    )
    assert events[-1] == (780, 780)
    assert all(a[0] < b[0] for a, b in zip(events, events[1:], strict=False))

    class RejectModel:
        audit = []
        stats = {}

        def predict(self, context):
            return {"allow_entry": False, "reason": "成本门槛未通过", "probability": 0.8}

    result = simulate(
        frame,
        StrategyConfig(fast=2, slow=3),
        "2024-01-03",
        "2024-01-04",
        model_filter=RejectModel(),
        record_market=True,
    )
    assert not result["trades"]
    assert any(
        p["rule_candidate"] and p["model_allow_entry"] is False for p in result["market_curve"]
    )
    assert result["market_curve"][-1]["equity"] == 100_000
