import json

import pytest
from quant_workbench.deployments import public_deployment, publish
from quant_workbench.market_data import demo_data
from quant_workbench.models import ExperimentInput
from quant_workbench.repository import Repository
from quant_workbench.research import create_experiment


def test_publication_only_transfers_independent_strategy_and_model(tmp_path):
    repo = Repository(tmp_path)
    ds = repo.save_dataset(demo_data(), "demo", "synthetic", True)
    exp = create_experiment(
        repo,
        ExperimentInput(
            dataset_id=ds["id"],
            symbols=["NVDA"],
            start="2024-01-02",
            train_end="2024-01-05",
            validation_end="2024-01-09",
            end="2024-01-11",
            model={"enabled": True, "k": 5, "max_iter": 1},
        ),
    )
    with pytest.raises(ValueError, match="完成验证"):
        publish(repo, exp["id"])
    with repo.connect() as db:
        db.execute("INSERT INTO runs VALUES (?, 'validation', 'completed', NULL, 0)", (exp["id"],))
    deployed = publish(repo, exp["id"])
    assert deployed == publish(repo, exp["id"])
    assert len(repo.list_records("deployments")) == 1
    assert deployed["id"] != exp["id"]
    assert deployed["strategies"] == exp["strategies"]
    forbidden = {
        "dataset_id",
        "profiles",
        "runs",
        "start",
        "train_end",
        "validation_end",
        "end",
        "model_metadata",
        "model_artifact",
        "experiment_id",
        "results",
    }
    assert not forbidden.intersection(deployed)
    assert "max_iter" not in deployed["model"]
    stored = repo.get("deployments", deployed["id"])
    model = repo.load_model(deployed["id"], stored["model_artifact"])
    assert model._states == {}
    assert not {"train_start", "train_end", "last_target_time"}.intersection(model.metadata)
    # Publication is self-contained even if the research record/artifact is unavailable.
    repo.path("models", exp["id"], ".joblib").unlink()
    with repo.connect() as db:
        db.execute("DELETE FROM experiments WHERE id=?", (exp["id"],))
    assert repo.load_model(deployed["id"], stored["model_artifact"]).estimator is not None
    assert public_deployment(repo.list_records("deployments")[0]) == deployed
    assert exp["id"] not in json.dumps(deployed)
