"""Local HTTP gateway. No repository, ML runtime or computation is loaded here."""

import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask


def compute_origin(value: str) -> str:
    try:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or (url.port is not None and not 1 <= url.port <= 65535)
        ):
            raise ValueError
    except ValueError as exc:
        raise HTTPException(422, "计算服务地址必须是 http(s)://服务器:端口") from exc
    return value.rstrip("/")


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(300, connect=5), trust_env=False,
    ) as client:
        app.state.compute_client = client
        yield


app = FastAPI(title="Quant Workbench Local Gateway", lifespan=lifespan)


@app.get("/local/health")
def health():
    return {"status": "ok", "service": "quant-workbench-local"}


@app.api_route("/api/{path:path}", methods=["GET", "POST"])
async def forward(path: str, request: Request):
    origin = compute_origin(request.headers.get(
        "x-quant-compute-url",
        os.environ.get("QUANT_COMPUTE_URL", "http://127.0.0.1:8001"),
    ))
    # Never forward browser cookies or Host to the chosen server.
    headers = {
        name: request.headers[name]
        for name in ("content-type", "accept") if name in request.headers
    }
    client = request.app.state.compute_client
    upstream = client.build_request(
        request.method,
        f"{origin}/api/{path}",
        params=request.query_params.multi_items(),
        headers=headers,
        content=request.stream(),
    )
    try:
        response = await client.send(upstream, stream=True)
    except httpx.RequestError as exc:
        raise HTTPException(
            502, "无法连接计算服务，请检查服务器、端口和网络；已提交任务可能仍在运行",
        ) from exc
    response_headers = {
        name: response.headers[name]
        for name in ("content-type", "content-disposition", "content-length", "content-encoding")
        if name in response.headers
    }
    return StreamingResponse(
        response.aiter_raw(), status_code=response.status_code,
        headers=response_headers, background=BackgroundTask(response.aclose),
    )
