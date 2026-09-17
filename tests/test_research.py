import numpy as np
import pandas as pd
import pytest
from quant_workbench.market_data import demo_data
from quant_workbench.models import ExperimentInput
from quant_workbench.repository import Repository
from quant_workbench.research import begin_run, create_experiment, execute_run


def test_frozen_training_profiles_final_gate_and_persistent_replay(tmp_path):
    repo = Repository(tmp_path)
    ds = repo.save_dataset(demo_data(), "demo", "synthetic-v1", True)
    request = ExperimentInput(
        dataset_id=ds["id"],
        symbols=["NVDA"],
        start="2024-01-02",
        train_end="2024-01-05",
        validation_end="2024-01-09",
        end="2024-01-11",
    )
    exp = create_experiment(repo, request)
    with pytest.raises(ValueError, match="验证"):
        begin_run(repo, exp["id"], "test")
    begin_run(repo, exp["id"], "validation")
    execute_run(repo, exp["id"], "validation")
    assert repo.runs(exp["id"])[0]["status"] == "completed"
    begin_run(repo, exp["id"], "test")
    execute_run(repo, exp["id"], "test")
    result = Repository(tmp_path).result(exp["id"], "test")
    assert result["start"] == "2024-01-09"
    assert result["synthetic"] is True
    assert begin_run(repo, exp["id"], "test")["launch"] is False
    exp2 = create_experiment(repo, request)
    assert begin_run(repo, exp2["id"], "validation")["prior_test_exposure"] is True


def test_test_prices_never_change_training_stock_profiles(tmp_path):
    repo = Repository(tmp_path)
    frame = demo_data()
    ds1 = repo.save_dataset(frame, "a", "csv")
    params = dict(
        symbols=["NVDA"],
        start="2024-01-02",
        train_end="2024-01-05",
        validation_end="2024-01-09",
        end="2024-01-11",
    )
    a = create_experiment(repo, ExperimentInput(dataset_id=ds1["id"], **params))
    mask = frame.timestamp >= pd.Timestamp("2024-01-09", tz="UTC")
    frame.loc[mask, ["open", "high", "low", "close"]] *= 10
    ds2 = repo.save_dataset(frame, "b", "csv")
    b = create_experiment(repo, ExperimentInput(dataset_id=ds2["id"], **params))
    assert a["profiles"] == b["profiles"]
    assert a["strategies"] == b["strategies"]


def test_modified_snapshot_is_rejected(tmp_path):
    repo = Repository(tmp_path)
    ds = repo.save_dataset(demo_data(), "demo", "synthetic", True)
    repo.path("datasets", ds["id"], ".parquet").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="哈希"):
        repo.load_dataset(ds["id"])


def test_online_phases_reload_offline_model_and_save_independent_checkpoints(tmp_path):
    repo = Repository(tmp_path)
    frame = demo_data()
    frame = frame[(frame.symbol == "NVDA") & (frame.timestamp < "2024-01-05")]
    ds = repo.save_dataset(frame, "online-demo", "synthetic", True)
    request = ExperimentInput(
        dataset_id=ds["id"],
        symbols=["NVDA"],
        start="2024-01-02",
        train_end="2024-01-03",
        validation_end="2024-01-04",
        end="2024-01-05",
        config={"strategy": "sma", "fast": 2, "slow": 5},
        model={"enabled": True, "k": 5, "max_iter": 1, "probability_threshold": 0.5},
    )
    experiment = create_experiment(repo, request)
    identifier, artifact = experiment["id"], experiment["model_artifact"]
    original = repo.load_model(identifier, artifact)
    assert original.stats["updates"] == 0
    assert original._states == {}
    assert pd.Timestamp(original.metadata["last_target_time"]) < pd.Timestamp(
        request.train_end, tz="UTC"
    )
    for phase, day in (("validation", "2024-01-03"), ("test", "2024-01-04")):
        assert begin_run(repo, identifier, phase)["launch"] is True
        execute_run(repo, identifier, phase)
        runs = {row["phase"]: row for row in repo.runs(identifier)}
        assert runs[phase]["status"] == "completed", runs[phase]
        result = repo.result(identifier, phase)
        statistics = result["model_statistics"]
        assert statistics["updates"] == 385
        assert statistics["warmup_bars"] == 10
        assert 0 <= statistics["brier_score"] <= 1
        assert statistics["log_loss"] >= 0
        assert statistics["baseline_log_loss"] >= 0
        audit = result["model_audit"]
        assert len(audit) == 390
        assert [row["observed_count"] for row in audit[:11]] == list(range(1, 12))
        assert all(row["probability"] is None and not row["allow_entry"] for row in audit[:10])
        assert audit[10]["warmup"] is False
        first_allowed_signal = pd.Timestamp(f"{day}T14:41:00Z")
        for trade in result["trades"]:
            if trade["side"] == "buy":
                assert pd.Timestamp(trade["signal_time"]) >= first_allowed_signal
                assert pd.Timestamp(trade["timestamp"]) > pd.Timestamp(trade["signal_time"])
        checkpoint = repo.load_model(f"{identifier}-{phase}", result["model_checkpoint"])
        assert checkpoint["states"]["NVDA"]["count"] == 390
        assert checkpoint["stats"]["updates"] == 385
        assert not np.array_equal(
            checkpoint["states"]["NVDA"]["estimator"].coef_, original.estimator.coef_
        )
        reloaded = repo.load_model(identifier, artifact)
        assert reloaded._states == {}
        assert reloaded.stats["updates"] == 0
        np.testing.assert_array_equal(reloaded.estimator.coef_, original.estimator.coef_)
