"""Persisted long-horizon research jobs; never sends brokerage orders."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_workbench.operations import begin_operation, get_operation, save_operation
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from quant_workbench.research import WORKER_GATE

router = APIRouter(prefix="/api/position")


class PositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    symbols: list[str] = Field(min_length=1, max_length=10)
    start: date
    end: date
    config: PositionConfig = Field(default_factory=PositionConfig)

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
            dataset = repo.get("datasets", request.dataset_id)
            frame = repo.load_dataset(request.dataset_id)
            frame = frame[frame.symbol.isin(request.symbols)]
            report("汇总日线并拟合仅含成熟标签的模型")
            result = simulate_positions(
                frame, request.config, str(request.start), str(request.end), progress=report,
            )
            result.update(dataset_id=request.dataset_id, dataset_sha256=dataset["sha256"],
                          synthetic=dataset["synthetic"], source=dataset["source"])
        job.update(status="completed", stage="长期持仓研究完成", result=result, done=1, total=1)
    except Exception as exc:
        job.update(status="failed", stage="长期研究失败", error=str(exc)[:500]
                   if isinstance(exc, (ValueError, KeyError)) else "计算失败，请检查数据或运行日志")
    job["finished_at"] = datetime.now(UTC).isoformat()
    save_operation(repo, job)


@router.post("/run")
def launch(request: PositionRequest, tasks: BackgroundTasks):
    repo = Repository()
    dataset = repo.get("datasets", request.dataset_id)
    if not set(request.symbols).issubset(dataset["symbols"]):
        raise ValueError("股票不在所选数据集中")
    job = begin_operation(repo, "position")
    job["request"] = request.model_dump(mode="json")
    save_operation(repo, job)
    tasks.add_task(execute, repo, job.copy(), request)
    return job


@router.get("/{identifier}/export")
def export(identifier: str):
    import pandas as pd

    job = get_operation(Repository(), identifier)
    if job["kind"] != "position" or job["status"] != "completed":
        raise ValueError("请等待长期任务完成再导出")
    return Response(
        pd.DataFrame(job["result"]["trades"]).to_csv(index=False).encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="position-{identifier}.csv"'},
    )
