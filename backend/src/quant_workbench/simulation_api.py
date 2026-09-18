from typing import Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import Response

from quant_workbench.portfolio_export import portfolio_rows
from quant_workbench.repository import Repository
from quant_workbench.simulations import (
    Scope,
    SimulationInput,
    begin_simulation,
    execute_simulation,
    get_job,
    list_jobs,
    snapshot,
)

router = APIRouter(prefix="/api")


@router.post("/{scope}/simulations")
def launch(scope: Scope, request: SimulationInput, tasks: BackgroundTasks):
    repo = Repository()
    job = begin_simulation(repo, scope, request)
    tasks.add_task(execute_simulation, repo, scope, job["id"])
    return job


@router.get("/{scope}/simulations")
def history(scope: Scope, source_id: str):
    return list_jobs(Repository(), scope, source_id)


@router.get("/{scope}/simulations/{identifier}")
def status(scope: Scope, identifier: str):
    return get_job(Repository(), scope, identifier)


@router.get("/{scope}/simulations/{identifier}/result")
def result(scope: Scope, identifier: str):
    return snapshot(Repository(), scope, identifier)


@router.get("/{scope}/simulations/{identifier}/export/{kind}")
def export(scope: Scope, identifier: str, kind: Literal[
    "trades", "market_curve", "daily_returns", "portfolio_curve", "allocation_decisions",
]):
    repo = Repository()
    if get_job(repo, scope, identifier)["status"] != "completed":
        raise ValueError("请在模拟完成后导出完整数据")
    rows = snapshot(repo, scope, identifier).get(kind, [])
    if kind == "portfolio_curve":
        rows = list(portfolio_rows(rows))
    return Response(
        pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{identifier}-{kind}.csv"'},
    )
