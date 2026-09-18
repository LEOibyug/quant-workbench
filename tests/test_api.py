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


def test_unified_pages_and_api_share_origin_without_swallowing_missing_api(tmp_path, monkeypatch):
    from quant_workbench import api

    (tmp_path / "index.html").write_text('<html><div id="root">workbench</div></html>')
    monkeypatch.setattr(api, "FRONTEND_DIR", tmp_path)
    for route in ("/", "/research", "/workspace?deployment=example"):
        response = get(route)
        assert response.status_code == 200
        assert 'id="root"' in response.text
        assert response.headers["cache-control"] == "no-cache"
    assert get("/api/health").json()["service"] == "quant-workbench"
    assert get("/api/unknown").status_code == 404
    (tmp_path / "index.html").unlink()
    assert get("/research").status_code == 503


def test_provider_catalog_missing_credentials_and_csv_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_DATA_DIR", str(tmp_path))
    for key in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "MASSIVE_API_KEY", "POLYGON_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            catalog = (await client.get("/api/providers")).json()
            assert {p["id"] for p in catalog} == {"alpaca", "massive"}
            assert not any(p["configured"] for p in catalog)
            for provider in ("alpaca", "massive"):
                response = await client.post(
                    "/api/datasets/fetch",
                    json={
                        "provider": provider,
                        "symbols": ["AAPL"],
                        "start": "2024-01-03",
                        "end": "2024-01-04",
                    },
                )
                assert response.status_code == 422
                assert "后端环境" in response.json()["detail"]
            response = await client.post(
                "/api/datasets/import",
                files={"file": ("invalid.csv", b"symbol,close\nAAPL,100\n", "text/csv")},
            )
            assert response.status_code == 422
            assert (await client.get("/api/datasets")).json() == []

    asyncio.run(run())
