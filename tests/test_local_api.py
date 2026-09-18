"""Gateway contracts: server isolation, streamed uploads/results, connection failures."""

import asyncio
import json

import httpx
from quant_workbench.local_api import app


def test_gateway_preserves_target_body_progress_and_download():
    async def run():
        seen = []

        async def upstream(request):
            seen.append((str(request.url), await request.aread(), request.headers))
            if request.url.path.endswith("/export"):
                return httpx.Response(
                    200, stream=httpx.ByteStream(b"symbol,pnl\nNVDA,42\n"),
                    headers={"content-type": "text/csv", "content-disposition": 'filename="r.csv"'},
                )
            return httpx.Response(200, stream=httpx.ByteStream(json.dumps({
                "status": "running", "done": 5, "total": 10,
            }).encode()), headers={"content-type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as remote:
            app.state.compute_client = remote
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://local",
            ) as client:
                headers = {"X-Quant-Compute-URL": "http://server-a:8001", "Cookie": "private=x"}
                response = await client.post(
                    "/api/datasets/import?tag=a&tag=b", headers=headers,
                    files={"file": ("bars.csv", b"symbol,close\nNVDA,100", "text/csv")},
                )
                assert response.json()["done"] == 5
                assert seen[0][0] == "http://server-a:8001/api/datasets/import?tag=a&tag=b"
                assert b"NVDA,100" in seen[0][1]
                assert "multipart/form-data" in seen[0][2]["content-type"]
                assert "cookie" not in seen[0][2]
                result = await client.get(
                    "/api/jobs/export", headers={"X-Quant-Compute-URL": "http://server-b:9001"},
                )
                assert seen[1][0] == "http://server-b:9001/api/jobs/export"
                assert result.content == b"symbol,pnl\nNVDA,42\n"
                assert result.headers["content-disposition"] == 'filename="r.csv"'

    asyncio.run(run())


def test_gateway_reports_unreachable_and_rejects_invalid_origin():
    async def run():
        def offline(request):
            raise httpx.ConnectError("offline", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as remote:
            app.state.compute_client = remote
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://local",
            ) as client:
                response = await client.get("/api/health")
                assert response.status_code == 502
                assert "已提交任务可能仍在运行" in response.json()["detail"]
                for target in ("file:///tmp/data", "http://host/path", "http://user:pw@host"):
                    response = await client.get(
                        "/api/health", headers={"X-Quant-Compute-URL": target},
                    )
                    assert response.status_code == 422
                assert (await client.get("/local/health")).json()["status"] == "ok"

    asyncio.run(run())
