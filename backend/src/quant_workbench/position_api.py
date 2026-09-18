"""Persisted long-horizon research jobs; never sends brokerage orders."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_workbench.daily_providers import fetch_daily
from quant_workbench.deployments import publish_position
from quant_workbench.models import ProviderInput
from quant_workbench.operations import begin_operation, get_operation, save_operation
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from quant_workbench.research import WORKER_GATE

router = APIRouter(prefix="/api/position")


class PositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    symbols: list[str] = Field(min_length=1, max_length=20)
    start: date
    end: date
    config: PositionConfig = Field(default_factory=PositionConfig)
    name: str = Field(default="长期持仓策略", min_length=1, max_length=120)
    provider: Literal["alpaca", "massive"] = "alpaca"
    feed: Literal["iex", "sip"] = "sip"

    @model_validator(mode="after")
    def dates(self):
        if self.start >= self.end:
            raise ValueError("开始日期必须早于结束日期（右端不含）")
        return self


def execute(repo, job, request):
    def report(stage, done=0, total=None, unit=""):
        job.update(status="running", stage=stage, done=done, total=total, unit=unit)
        save_operation(repo, job)

    try:
        report("等待长期模型计算资源")
        with WORKER_GATE:
            if request.dataset_id:
                dataset = repo.get("datasets", request.dataset_id)
                frame = repo.load_dataset(request.dataset_id)
                frame = frame[frame.symbol.isin(request.symbols)]
                if dataset.get("timeframe", "1Min") != "1Day":
                    raise ValueError("长期策略统一使用日线，请在数据下载中选择长期日线后重新运行")
                daily_bars = True
                source = dataset["source"]
            else:
                since = request.start - timedelta(days=240)
                market_request = ProviderInput(
                    symbols=request.symbols, start=since, end=request.end,
                    provider=request.provider, feed=request.feed,
                )
                key = hashlib.sha256(
                    market_request.model_dump_json().encode(),
                ).hexdigest()
                cache_dir = repo.root / "workspace" / "daily"
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path = cache_dir / f"{key}.parquet"
                report("加载独立日线缓存" if cache_path.exists() else "获取日线与模型预热历史")
                frame = (pd.read_parquet(cache_path) if cache_path.exists() else
                         fetch_daily(market_request, progress=report))
                daily_bars = True
                feed = request.feed if request.provider == "alpaca" else "raw"
                source = f"{request.provider}-{feed}-daily"
            if not set(request.symbols).issubset(set(frame.symbol)):
                raise ValueError("行情未包含所选股票，请检查供应商权限和日期")
            report("拟合仅含成熟标签的日线模型")
            result = simulate_positions(
                frame, request.config, str(request.start), str(request.end), progress=report,
                daily_bars=daily_bars,
            )
            if not request.dataset_id:
                # Only cache validated data; do not retain partial provider responses.
                temporary = cache_path.with_suffix(".tmp.parquet")
                frame.to_parquet(temporary, index=False)
                temporary.replace(cache_path)
                result.update(synthetic=False, source=source)
            else:
                result.update(dataset_id=request.dataset_id, dataset_sha256=dataset["sha256"],
                              synthetic=dataset["synthetic"], source=source)
        job.update(status="completed", stage="长期持仓研究完成", result=result, done=1, total=1)
    except Exception as exc:
        job.update(status="failed", stage="长期研究失败", error=str(exc)[:500]
                   if isinstance(exc, (ValueError, KeyError)) else "计算失败，请检查数据或运行日志")
    job["finished_at"] = datetime.now(UTC).isoformat()
    save_operation(repo, job)


@router.post("/run")
def launch(request: PositionRequest, tasks: BackgroundTasks):
    repo = Repository()
    if request.dataset_id is None:
        raise ValueError("长期研究请选择行情数据集")
    dataset = repo.get("datasets", request.dataset_id)
    if dataset.get("timeframe", "1Min") != "1Day":
        raise ValueError("长期研究需日线数据集，请下载长期日线")
    if not set(request.symbols).issubset(dataset["symbols"]):
        raise ValueError("股票不在所选数据集中")
    job = begin_operation(repo, "position")
    job["request"] = request.model_dump(mode="json")
    save_operation(repo, job)
    tasks.add_task(execute, repo, job.copy(), request)
    return job


@router.post("/{identifier}/publish")
def publish(identifier: str):
    return publish_position(Repository(), identifier)


@router.get("/history")
def history(deployment_id: str | None = None):
    with Repository().connect() as db:
        jobs = [json.loads(row[0]) for row in db.execute("SELECT body FROM operations")]
    return sorted([
        {key: job.get(key) for key in ("id", "status", "started_at", "request")}
        for job in jobs
        if (job["kind"] == "position" if deployment_id is None else
            job["kind"] == "position_simulation" and job.get("deployment_id") == deployment_id)
    ], key=lambda job: job["started_at"], reverse=True)


class PositionSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] | None = Field(default=None, min_length=1, max_length=20)
    provider: Literal["alpaca", "massive"] = "alpaca"
    feed: Literal["iex", "sip"] = "sip"
    dataset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    start: date
    end: date


@router.post("/deployments/{identifier}/simulate")
def simulate_deployment(
    identifier: str, request: PositionSimulationRequest, tasks: BackgroundTasks,
):
    repo = Repository()
    deployment = repo.get("deployments", identifier)
    if deployment.get("horizon_type") != "long":
        raise ValueError("请选择长期策略版本")
    symbols = list(dict.fromkeys(request.symbols or deployment["symbols"]))
    if not set(symbols).issubset(deployment["symbols"]):
        raise ValueError("股票不在已发布策略的支持范围内")
    frozen = PositionRequest(
        **request.model_dump(exclude={"symbols"}), symbols=symbols,
        config=deployment["position_config"], name=deployment["name"],
    )
    if request.dataset_id:
        dataset = repo.get("datasets", request.dataset_id)
        if dataset.get("timeframe", "1Min") != "1Day":
            raise ValueError("长期模拟需日线数据集，请下载长期日线")
        if not set(frozen.symbols).issubset(dataset["symbols"]):
            raise ValueError("行情数据集必须包含所选股票")
    job = begin_operation(repo, "position_simulation")
    job.update(request=frozen.model_dump(mode="json"), deployment_id=identifier)
    save_operation(repo, job)
    tasks.add_task(execute, repo, job.copy(), frozen)
    return job


@router.get("/{identifier}/export")
def export(identifier: str):
    import pandas as pd

    job = get_operation(Repository(), identifier)
    if job["kind"] not in {"position", "position_simulation"} or job["status"] != "completed":
        raise ValueError("请等待长期任务完成再导出")
    return Response(
        pd.DataFrame(job["result"]["trades"]).to_csv(index=False).encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="position-{identifier}.csv"'},
    )


@router.get("/{identifier}/export/{kind}")
def export_details(identifier: str, kind: Literal["curve", "allocations"]):
    from quant_workbench.portfolio_export import portfolio_rows

    job = get_operation(Repository(), identifier)
    if job["kind"] not in {"position", "position_simulation"} or job["status"] != "completed":
        raise ValueError("请等待长期任务完成再导出")
    result = job["result"]
    rows = (list(portfolio_rows(result["curve"])) if kind == "curve" else
            result.get("allocation_decisions", []))
    return Response(
        pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="position-{identifier}-{kind}.csv"'},
    )
