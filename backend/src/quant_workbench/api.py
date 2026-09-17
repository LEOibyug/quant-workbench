"""Loopback-only development API. Trading capabilities are not implemented."""

from dataclasses import asdict
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from quant_workbench.storage import estimate_storage

app = FastAPI(title="Quant Workbench", version="0.1.0")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "stage": "project-foundation",
        "market_data_connected": False,
        "backtest_available": False,
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
