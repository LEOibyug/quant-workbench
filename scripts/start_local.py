"""Supervise the local gateway and Vite as one foreground service."""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="启动本地网关和网页，Ctrl+C 停止两者")
    parser.add_argument("--api-port", type=int, default=8000, help="网关端口，0 为自动分配")
    parser.add_argument("--web-port", type=int, default=5173, help="网页端口")
    args = parser.parse_args()
    if not 0 <= args.api_port <= 65535 or not 1 <= args.web_port <= 65535:
        parser.error("网关端口为 0–65535，网页端口为 1–65535")
    children = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", args.api_port))
            listener.listen(128)
            api_port = listener.getsockname()[1]
            with socket.socket() as check:
                check.bind(("127.0.0.1", args.web_port))
            env = dict(os.environ, QUANT_API_TARGET=f"http://127.0.0.1:{api_port}")
            gateway = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "quant_workbench.local_api:app",
                 "--app-dir", str(ROOT / "backend/src"), "--fd", str(listener.fileno())],
                cwd=ROOT, env=env, pass_fds=(listener.fileno(),), start_new_session=True,
            )
            children.append(gateway)
            web = subprocess.Popen(
                ["node", str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
                 "--host", "127.0.0.1", "--port", str(args.web_port), "--strictPort"],
                cwd=ROOT / "frontend", env=env, start_new_session=True,
            )
            children.append(web)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            ready = False
            deadline = time.monotonic() + 30
            while not stopping:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("本地服务提前退出，请检查上方日志")
                if not ready:
                    try:
                        for url in (f"http://127.0.0.1:{api_port}/local/health",
                                    f"http://127.0.0.1:{args.web_port}/research"):
                            with opener.open(url, timeout=1) as response:
                                if response.status != 200:
                                    raise OSError("服务尚未就绪")
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError("启动超时，请检查上方日志") from None
                    else:
                        ready = True
                        print(
                            f"\n本地工作台：http://127.0.0.1:{args.web_port}/research", flush=True,
                        )
                        print(f"本地网关：http://127.0.0.1:{api_port}", flush=True)
                        print("在网页顶部填写计算服务器和端口。Ctrl+C 停止本地服务。", flush=True)
                time.sleep(0.2)
    except (OSError, RuntimeError) as exc:
        print(f"启动失败：{exc}；可用 --api-port / --web-port 更换端口。", file=sys.stderr)
        return 1
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
