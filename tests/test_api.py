import asyncio

import httpx
from quant_workbench.api import app


def get(path):
    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_health_does_not_claim_unimplemented_trading_capabilities():
    response = get("/api/health")
    assert response.status_code == 200
    assert response.json()["market_data_connected"] is False
    assert response.json()["live_trading_enabled"] is False


def test_storage_estimate_and_validation_over_http():
    response = get("/api/storage-estimate?symbols=3&years=1")
    assert response.status_code == 200
    assert response.json()["rows"] == 294_840
    assert get("/api/storage-estimate?symbols=0").status_code == 422
    assert get("/api/storage-estimate?years=nan").status_code == 422
    assert get("/api/storage-estimate?interval_seconds=7").status_code == 422
