"""Immutable experiments and chronological evaluation."""

import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime

from quant_workbench.engine import ENGINE_VERSION, simulate
from quant_workbench.market_data import require_complete
from quant_workbench.models import ExperimentInput, StrategyConfig
from quant_workbench.profiles import analyze_stocks
from quant_workbench.repository import Repository
from quant_workbench.timeseries import TimeSeriesConfig, train_model

WORKER_GATE = threading.BoundedSemaphore(1)
PHASES = {"train", "validation", "test"}


def create_experiment(repo: Repository, request: ExperimentInput) -> dict:
    dataset = repo.get("datasets", request.dataset_id)
    if not set(request.symbols).issubset(dataset["symbols"]):
        raise ValueError("所选股票不在数据集中")
    frame = repo.load_dataset(request.dataset_id)
    frame = frame[frame.symbol.isin(request.symbols)]
    require_complete(frame, str(request.start), str(request.end))
    train = require_complete(frame, str(request.start), str(request.train_end))
    require_complete(frame, str(request.train_end), str(request.validation_end))
    require_complete(frame, str(request.validation_end), str(request.end))
    profiles = analyze_stocks(train)
    strategies = {
        p["symbol"]: p["suggested_strategy"]
        if request.config.strategy == "adaptive"
        else request.config.strategy
        for p in profiles
    }
    model = TimeSeriesConfig.model_validate(request.model)
    info = request.model_dump(mode="json")
    info["model"] = model.model_dump()
    info.update(
        {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(UTC).isoformat(),
            "dataset_sha256": dataset["sha256"],
            "synthetic": dataset["synthetic"],
            "source": dataset["source"],
            "profiles": profiles,
            "strategies": strategies,
            "engine_version": ENGINE_VERSION,
            "profile_period": {"start": str(request.start), "end": str(request.train_end)},
        }
    )
    if model.enabled:
        trained = train_model(train, model)
        info["model_metadata"] = trained.metadata
        info["model_artifact"] = repo.save_model(info["id"], trained)
    info["config_sha256"] = hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()
    repo.save_experiment(info)
    return info


def begin_run(repo: Repository, identifier: str, phase: str) -> dict:
    if phase not in PHASES:
        raise ValueError("未知运行阶段")
    experiment = repo.get("experiments", identifier)
    with repo.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM runs WHERE experiment_id=? AND phase=?", (identifier, phase)
        ).fetchone()
        if existing and existing["status"] in {"running", "completed"}:
            return {"status": existing["status"], "launch": False}
        if phase == "test":
            validated = db.execute(
                "SELECT status FROM runs WHERE experiment_id=? AND phase='validation'",
                (identifier,),
            ).fetchone()
            if not validated or validated["status"] != "completed":
                raise ValueError("最终测试之前必须先完成验证阶段；参数和股票策略已冻结")
        if db.execute("SELECT 1 FROM runs WHERE status='running'").fetchone():
            raise ValueError("已有任务在运行，请等待完成后再启动")
        prior_exposure = False
        for row in db.execute(
            "SELECT e.body FROM experiments e JOIN runs r ON e.id=r.experiment_id "
            "WHERE r.phase='test' AND r.exposed=1"
        ):
            previous = json.loads(row[0])
            if (
                set(previous["symbols"]) & set(experiment["symbols"])
                and previous["validation_end"] < experiment["end"]
                and experiment["start"] < previous["end"]
            ):
                prior_exposure = True
        db.execute(
            "INSERT INTO runs(experiment_id,phase,status,error,exposed) "
            "VALUES(?,?,'running',NULL,?) "
            "ON CONFLICT(experiment_id,phase) DO UPDATE SET status='running',error=NULL",
            (identifier, phase, int(phase == "test")),
        )
    return {"status": "running", "launch": True, "prior_test_exposure": prior_exposure}


def execute_run(repo: Repository, identifier: str, phase: str, exposure=False):
    try:
        with WORKER_GATE:
            info = repo.get("experiments", identifier)
            boundaries = {
                "train": (info["start"], info["train_end"]),
                "validation": (info["train_end"], info["validation_end"]),
                "test": (info["validation_end"], info["end"]),
            }
            start, end = boundaries[phase]
            frame = repo.load_dataset(info["dataset_id"])
            frame = frame[frame.symbol.isin(info["symbols"])]
            model_config = TimeSeriesConfig.model_validate(info["model"])
            filter_instance = (
                repo.load_model(identifier, info["model_artifact"])
                if model_config.enabled
                else None
            )
            result = simulate(
                frame,
                StrategyConfig(**info["config"]),
                start,
                end,
                info["strategies"],
                filter_instance,
            )
            result.update(
                {
                    "experiment_id": identifier,
                    "phase": phase,
                    "start": start,
                    "end": end,
                    "synthetic": info["synthetic"],
                    "source": info["source"],
                    "config_sha256": info["config_sha256"],
                    "dataset_sha256": info["dataset_sha256"],
                    "prior_test_exposure": exposure,
                    "model_enabled": model_config.enabled,
                    "in_sample": phase == "train",
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )
            if model_config.enabled:
                result["rule_baseline"] = simulate(
                    frame, StrategyConfig(**info["config"]), start, end, info["strategies"]
                )["metrics"]
                result["model_checkpoint"] = repo.save_model(
                    identifier, filter_instance.checkpoint_state(), phase
                )
                result["assumptions"].extend(
                    [
                        "每阶段从同一离线模型初始化；每股独立按已成熟标签在线适应，前2k周期不入场",
                        "预测目标是下一分钟收盘收益超过min_return_bps，非扣费盈利概率；阈值未经校准",
                        "模型学习与推理延迟未另行计入；需在实盘接入前测量延迟和真实成交成本",
                    ]
                )
                if phase == "train":
                    result["assumptions"].append("开发期回放属于样本内结果，离线训练已见该阶段数据")
            repo.save_result(identifier, phase, result)
    except Exception as exc:
        message = (
            str(exc)[:500]
            if isinstance(exc, ValueError)
            else "运行失败，请检查数据或重启服务后重试"
        )
        with repo.connect() as db:
            db.execute(
                "UPDATE runs SET status='failed',error=? WHERE experiment_id=? AND phase=?",
                (message, identifier, phase),
            )
