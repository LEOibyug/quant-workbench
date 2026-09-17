"""Bounded, persisted research download/training jobs with measured stage progress."""

import json
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks

from quant_workbench.models import ExperimentInput, ProviderInput
from quant_workbench.providers import fetch_provider
from quant_workbench.repository import Repository
from quant_workbench.research import WORKER_GATE, create_experiment

router = APIRouter(prefix="/api/research/operations")


def get_operation(repo, identifier):
    with repo.connect() as db:
        row = db.execute("SELECT body FROM operations WHERE id=?", (identifier,)).fetchone()
    if row is None:
        raise KeyError("任务不存在或服务已重置")
    return json.loads(row[0])


def save_operation(repo, job):
    with repo.connect() as db:
        db.execute("UPDATE operations SET body=? WHERE id=?", (json.dumps(job), job["id"]))


def begin_operation(repo, kind):
    job = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "status": "queued",
        "stage": "等待开始",
        "done": 0,
        "total": None,
        "unit": "",
        "started_at": datetime.now(UTC).isoformat(),
        "error": None,
        "result": None,
    }
    with repo.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT body FROM operations"):
            other = json.loads(row[0])
            if other["kind"] == kind and other["status"] in {"queued", "running"}:
                raise ValueError("同类任务仍在执行，请等待完成")
        db.execute("INSERT INTO operations VALUES (?,?)", (job["id"], json.dumps(job)))
    return job


def execute_operation(repo, job, request):
    last_saved = 0.0
    last_stage = None

    def report(stage, done=0, total=None, unit=""):
        nonlocal last_saved, last_stage
        if stage == last_stage and done != total and time.monotonic() - last_saved < 0.4:
            return
        job.update(status="running", stage=stage, done=done, total=total, unit=unit)
        save_operation(repo, job)
        last_saved, last_stage = time.monotonic(), stage

    try:
        if job["kind"] == "download":
            report("连接供应商，等待第一页行情")
            frame = fetch_provider(request, progress=report)
            report("校验并保存本地行情快照")
            suffix = f"-{request.feed}" if request.provider == "alpaca" else ""
            result = repo.save_dataset(
                frame,
                f"{request.provider}{suffix} {request.start}—{request.end}",
                f"{request.provider}{suffix}-raw",
            )
        else:
            report("等待模型计算资源")
            with WORKER_GATE:
                result = create_experiment(repo, request, progress=report)
        job.update(
            status="completed",
            stage="下载完成" if job["kind"] == "download" else "训练并冻结完成",
            done=1,
            total=1,
            unit="任务",
            result=result,
            finished_at=datetime.now(UTC).isoformat(),
        )
    except Exception as exc:
        job.update(
            status="failed",
            stage="任务失败",
            error=str(exc)[:500]
            if isinstance(exc, ValueError)
            else "任务失败，请检查数据、模型依赖或供应商连接",
            finished_at=datetime.now(UTC).isoformat(),
        )
    save_operation(repo, job)


@router.post("/download")
def download(request: ProviderInput, tasks: BackgroundTasks):
    repo = Repository()
    job = begin_operation(repo, "download")
    tasks.add_task(execute_operation, repo, job.copy(), request)
    return job


@router.post("/train")
def train(request: ExperimentInput, tasks: BackgroundTasks):
    repo = Repository()
    job = begin_operation(repo, "train")
    tasks.add_task(execute_operation, repo, job.copy(), request)
    return job


@router.get("/{identifier}")
def status(identifier: str):
    return get_operation(Repository(), identifier)
