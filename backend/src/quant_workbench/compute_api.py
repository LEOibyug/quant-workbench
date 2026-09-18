"""Independent compute service: owns datasets, models, jobs and persisted results."""

from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from quant_workbench.operations import router as operations_router
from quant_workbench.repository import Repository
from quant_workbench.research_api import router
from quant_workbench.simulation_api import router as simulation_router
from quant_workbench.storage import estimate_storage


@asynccontextmanager
async def lifespan(app):
    Repository().recover()
    yield


app = FastAPI(title="Quant Workbench Compute", version="0.3.0", lifespan=lifespan)
app.include_router(router)
app.include_router(operations_router)
app.include_router(simulation_router)


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)[:500]})


@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)[:200]})


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "quant-workbench-compute",
        "protocol_version": 1,
        "stage": "historical-research",
        "market_data_connected": False,
        "backtest_available": True,
        "live_trading_enabled": False,
    }


@app.get("/api/storage-estimate")
def storage_estimate(
    symbols: Annotated[int, Query(ge=1, le=10_000)] = 7,
    years: Annotated[float, Query(gt=0, le=100, allow_inf_nan=False)] = 2,
    interval_seconds: Annotated[int, Query(ge=1, le=23_400)] = 60,
) -> dict:
    try:
        return asdict(estimate_storage(symbols, years, interval_seconds=interval_seconds))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
