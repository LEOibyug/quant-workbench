"""Single-stock simulations with scoped storage and observable, causal prefixes."""

import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_workbench.engine import ENGINE_VERSION, simulate
from quant_workbench.market_data import demo_data, normalize_bars
from quant_workbench.models import ProviderInput, StrategyConfig
from quant_workbench.providers import fetch_provider
from quant_workbench.repository import Repository
from quant_workbench.research import WORKER_GATE, has_prior_exposure

Scope = Literal["research", "workspace"]


class SimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    start: date
    end: date
    initial_cash: float = Field(default=100_000, ge=100, le=100_000_000)
    phase: Literal["train", "validation", "test"] = "validation"
    provider: Literal["alpaca", "massive", "demo"] = "alpaca"
    feed: Literal["iex", "sip"] = "sip"

    @model_validator(mode="after")
    def dates(self):
        if self.start >= self.end:
            raise ValueError("开始日期必须早于结束日期，结束日期不含在内")
        return self


def save_job(repo, job):
    with repo.connect() as db:
        db.execute(
            "INSERT INTO simulations VALUES (?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET body=excluded.body",
            (job["id"], job["scope"], json.dumps(job)),
        )


def get_job(repo, scope, identifier):
    with repo.connect() as db:
        row = db.execute(
            "SELECT body FROM simulations WHERE scope=? AND id=?", (scope, identifier)
        ).fetchone()
    if row is None:
        raise KeyError("模拟不存在")
    return json.loads(row[0])


def list_jobs(repo, scope, source_id):
    with repo.connect() as db:
        rows = db.execute(
            "SELECT body FROM simulations WHERE scope=? ORDER BY rowid DESC", (scope,)
        ).fetchall()
    return [j for row in rows if (j := json.loads(row[0]))["source_id"] == source_id][:50]


def result_path(repo, scope, identifier):
    folder = f"simulations/{scope}"
    (repo.root / folder).mkdir(parents=True, exist_ok=True)
    return repo.path(folder, identifier, ".json")


def save_snapshot(repo, job, body):
    path = result_path(repo, job["scope"], job["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def snapshot(repo, scope, identifier):
    get_job(repo, scope, identifier)
    path = result_path(repo, scope, identifier)
    return json.loads(path.read_text()) if path.exists() else {"market_curve": [], "trades": []}


def begin_simulation(repo: Repository, scope: Scope, request: SimulationInput):
    source = repo.get("experiments" if scope == "research" else "deployments", request.source_id)
    if source.get("horizon_type") == "long":
        raise ValueError("长期版本请使用长期组合模拟入口")
    if request.symbol not in source["symbols"]:
        raise ValueError("股票不在此策略/模型的支持范围内")
    start, end = str(request.start), str(request.end)
    warnings = []
    if source["model"].get("decision_mode") == "risk_scaled":
        warnings.append("模型调节风险预算；规则检查成本空间，不代表模型预测期望收益已覆盖成本")
    if scope == "research":
        bounds = {
            "train": (source["start"], source["train_end"]),
            "validation": (source["train_end"], source["validation_end"]),
            "test": (source["validation_end"], source["end"]),
        }
        lower, upper = bounds[request.phase]
        if not lower <= start < end <= upper:
            raise ValueError("模拟日期必须位于所选开发/验证/测试区间内")
        if request.phase == "test" and not any(
            r["phase"] == "validation" and r["status"] == "completed"
            for r in repo.runs(source["id"])
        ):
            raise ValueError("最终测试前必须完成冻结实验的完整验证阶段")
        if request.phase == "train":
            warnings.append("开发期属于样本内回放，模型离线训练已见此阶段数据")
        if request.phase == "test":
            warnings.append("查看此测试区间即构成测试集暴露，后续调参须使用新的未见数据")
    elif source["model"]["enabled"]:
        boundary = source.get("model_valid_from")
        if boundary and start < boundary:
            raise ValueError(f"此模型仅允许在 {boundary} 及之后进行样本外模拟")
        if not boundary:
            warnings.append("旧发布版本未记录训练截止日期；结果仅作探索，不可视为样本外验证")
    synthetic = source["synthetic"] if scope == "research" else request.provider == "demo"
    if synthetic:
        warnings.append("合成行情演示，非真实市场表现")
    if scope == "workspace" and source["synthetic"]:
        warnings.append("此策略/模型发布自合成数据实验")
    job = {
        **request.model_dump(mode="json"),
        "id": uuid.uuid4().hex,
        "scope": scope,
        "status": "queued",
        "stage": "等待计算",
        "completed_bars": 0,
        "total_bars": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "error": None,
        "synthetic": synthetic,
        "warnings": warnings,
        "engine_version": ENGINE_VERSION,
        "source_version": source.get("version", source.get("config_sha256")),
        "config": {
            **source.get("strategy_config", source.get("config", {})),
            "initial_cash": request.initial_cash,
        },
    }
    # Persist before execution, including failures: viewing test data remains an exposure.
    with repo.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT body FROM simulations"):
            if json.loads(row[0])["status"] in {"queued", "running"}:
                raise ValueError("已有单股模拟正在运行，请完成后再提交")
        if scope == "research" and has_prior_exposure(db, [request.symbol], start, end):
            job["warnings"].append("此股票区间与已暴露的测试/展示模拟重叠，不可再视为未见数据")
            job["prior_test_exposure"] = True
        db.execute(
            "INSERT INTO simulations VALUES (?,?,?)", (job["id"], job["scope"], json.dumps(job))
        )
    return job


def execute_simulation(repo: Repository, scope: Scope, identifier: str):
    job = get_job(repo, scope, identifier)
    try:
        with WORKER_GATE:
            job.update(status="running", stage="加载行情")
            save_job(repo, job)

            def fetching(stage, done=0, total=None, unit=""):
                job.update(
                    stage=stage, download_progress={"done": done, "total": total, "unit": unit}
                )
                save_job(repo, job)

            source = repo.get(
                "experiments" if scope == "research" else "deployments", job["source_id"]
            )
            if scope == "research":
                frame = repo.load_dataset(source["dataset_id"])
                job["data_source"] = source["source"]
            else:
                # Independent provider download/cache; never read a research dataset/result.
                cache = Repository(repo.root / "workspace")
                since = date.fromisoformat(job["start"]) - timedelta(days=45)
                cache_key = f"{job['provider']}:{job['feed']}:{job['symbol']}:{since}:{job['end']}"
                cached = next(
                    (d for d in cache.list_records("datasets") if d["name"] == cache_key), None
                )
                if cached:
                    frame = cache.load_dataset(cached["id"])
                else:
                    frame = (
                        demo_data()
                        if job["provider"] == "demo"
                        else fetch_provider(
                            ProviderInput(
                                provider=job["provider"],
                                feed=job["feed"],
                                symbols=[job["symbol"]],
                                start=since,
                                end=job["end"],
                            ),
                            progress=fetching,
                        )
                    )
                    frame = normalize_bars(frame[frame.symbol == job["symbol"]])
                    cache.save_dataset(frame, cache_key, job["provider"], job["synthetic"])
                job["data_source"] = f"{job['provider']}/{job['feed']}"
            frame = frame[frame.symbol == job["symbol"]]
            model = (
                repo.load_model(source["id"], source["model_artifact"])
                if source["model"]["enabled"]
                else None
            )
            job.update(stage="逐分钟模拟")
            save_job(repo, job)
            last_saved = 0.0

            def progress(done, total, curve, trades):
                nonlocal last_saved
                if time.monotonic() - last_saved < 0.5 and done != total:
                    return
                save_snapshot(repo, job, {"market_curve": curve, "trades": trades})
                job.update(completed_bars=done, total_bars=total)
                save_job(repo, job)
                last_saved = time.monotonic()

            result = simulate(
                frame,
                StrategyConfig(**job["config"]),
                job["start"],
                job["end"],
                {job["symbol"]: source["strategies"][job["symbol"]]},
                model,
                record_market=True,
                progress=progress,
            )
            save_snapshot(repo, job, result)
            job.update(
                status="completed", stage="模拟完成", completed_at=datetime.now(UTC).isoformat()
            )
            save_job(repo, job)
    except Exception as exc:
        job.update(
            status="failed",
            stage="模拟失败",
            error=str(exc)[:500]
            if isinstance(exc, ValueError)
            else "模拟失败，请检查数据和模型版本后重试",
        )
        save_job(repo, job)
