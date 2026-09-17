"""Publish independent strategy/model snapshots; never export research records."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from quant_workbench.repository import Repository


def publish(repo: Repository, experiment_id: str) -> dict:
    # Serialize publication so repeated clicks do not create competing versions.
    with repo.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT body FROM deployments WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
        if existing:
            return public_deployment(json.loads(existing[0]))
        experiment = repo.get("experiments", experiment_id)
        if not any(
            run["phase"] == "validation" and run["status"] == "completed"
            for run in repo.runs(experiment_id)
        ):
            raise ValueError("先在研究页完成验证，再发布策略与模型")
        identifier = uuid.uuid4().hex
        body = {
            "id": identifier,
            "name": experiment["name"],
            "published_at": datetime.now(UTC).isoformat(),
            "symbols": experiment["symbols"],
            "strategies": experiment["strategies"],
            "strategy_config": experiment["config"],
            "synthetic": experiment["synthetic"],
            "model": {
                key: value
                for key, value in experiment["model"].items()
                if key
                in {
                    "enabled",
                    "k",
                    "horizon",
                    "architecture",
                    "neural_learning_rate",
                    "neural_online_learning_rate",
                    "online_batch_size",
                    "replay_size",
                    "rbf_components",
                    "probability_threshold",
                    "online_learning_rate",
                    "min_return_bps",
                    "adapt",
                    "cost_aware",
                    "cost_multiplier",
                    "min_edge_bps",
                }
            },
            "engine_version": experiment["engine_version"],
        }
        if body["model"]["enabled"]:
            model = repo.load_model(experiment_id, experiment["model_artifact"])
            # Only learned weights, preprocessing, inference/adaptation config are transferred.
            model.metadata = {
                key: value
                for key, value in model.metadata.items()
                if key
                in {
                    "model_version",
                    "torch_version",
                    "architecture",
                    "parameter_count",
                    "feature_names",
                    "sklearn_version",
                    "class_balance",
                    "feedback_features",
                    "transformed_features",
                }
            }
            body["model_artifact"] = repo.save_model(identifier, model)
            body["model_version"] = model.metadata["model_version"]
        body["version"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
        db.execute(
            "INSERT INTO deployments VALUES (?,?,?)",
            (identifier, experiment_id, json.dumps(body)),
        )
    return public_deployment(body)


def public_deployment(body: dict) -> dict:
    # An explicit allowlist avoids accidentally exposing future research fields.
    fields = {
        "id",
        "name",
        "published_at",
        "symbols",
        "strategies",
        "strategy_config",
        "synthetic",
        "model",
        "model_version",
        "version",
        "engine_version",
    }
    return {key: value for key, value in body.items() if key in fields}
