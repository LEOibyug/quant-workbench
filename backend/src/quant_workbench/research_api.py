import io
import os
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import Response

from quant_workbench.market_data import demo_data
from quant_workbench.models import AlpacaInput, ExperimentInput, ProviderInput
from quant_workbench.providers import fetch_alpaca, fetch_provider, provider_catalog
from quant_workbench.repository import Repository
from quant_workbench.research import begin_run, create_experiment, execute_run

router = APIRouter(prefix="/api")
Phase = Literal["train", "validation", "test"]


@router.get("/capabilities")
def capabilities():
    return {
        "alpaca_configured": bool(
            os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY")
        ),
        "timeseries_available": True,
        "live_trading_enabled": False,
    }


@router.get("/providers")
def providers():
    return provider_catalog()


@router.post("/datasets/fetch")
def fetch(request: ProviderInput):
    suffix = f"-{request.feed}" if request.provider == "alpaca" else ""
    return Repository().save_dataset(
        fetch_provider(request),
        f"{request.provider}{suffix} {request.start}—{request.end}",
        f"{request.provider}{suffix}-raw",
    )


@router.get("/datasets")
def datasets():
    return Repository().list_records("datasets")


@router.post("/datasets/demo")
def demo():
    repo = Repository()
    for dataset in repo.list_records("datasets"):
        if dataset["source"] == "synthetic-v1":
            return dataset
    return repo.save_dataset(
        demo_data(), "合成演示 · 2024年1—2月 · 非真实行情", "synthetic-v1", True
    )


@router.post("/datasets/import")
def import_csv(file: Annotated[UploadFile, File()]):
    raw = file.file.read(100_000_001)
    if len(raw) > 100_000_000:
        raise HTTPException(413, "CSV上限100MB，请缩小范围")
    try:
        frame = pd.read_csv(io.BytesIO(raw))
        return Repository().save_dataset(frame, file.filename or "导入CSV", "user-csv")
    except (ValueError, UnicodeError, pd.errors.ParserError) as exc:
        raise HTTPException(422, str(exc)[:300]) from exc


@router.post("/datasets/alpaca")
def alpaca(request: AlpacaInput):
    return Repository().save_dataset(
        fetch_alpaca(request),
        f"Alpaca {request.feed} {request.start}—{request.end}",
        f"alpaca-{request.feed}-raw",
    )


@router.get("/experiments")
def experiments():
    repo = Repository()
    return [{**e, "runs": repo.runs(e["id"])} for e in repo.list_records("experiments")]


@router.post("/experiments")
def create(request: ExperimentInput):
    return create_experiment(Repository(), request)


@router.get("/experiments/{identifier}")
def experiment(identifier: str):
    repo = Repository()
    return {**repo.get("experiments", identifier), "runs": repo.runs(identifier)}


@router.post("/experiments/{identifier}/run/{phase}")
def run(identifier: str, phase: Phase, tasks: BackgroundTasks):
    repo = Repository()
    status = begin_run(repo, identifier, phase)
    if status["launch"]:
        tasks.add_task(execute_run, repo, identifier, phase, status["prior_test_exposure"])
    return status


@router.get("/experiments/{identifier}/results/{phase}")
def result(identifier: str, phase: Phase):
    body = Repository().result(identifier, phase)
    body["total_trades"] = len(body["trades"])
    body["trades"] = body["trades"][:300]
    curve = body["curve"]
    step = max(1, len(curve) // 1500)
    body["curve"] = curve[::step]
    if body["curve"][-1] != curve[-1]:
        body["curve"].append(curve[-1])
    body["curve_downsampled"] = step > 1
    return body


@router.get("/experiments/{identifier}/export/{phase}/{kind}")
def export(identifier: str, phase: Phase, kind: Literal["trades", "curve", "daily_returns"]):
    rows = Repository().result(identifier, phase)[kind]
    output = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
    return Response(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{identifier}-{phase}-{kind}.csv"'},
    )
