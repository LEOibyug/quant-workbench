"""Reserve a free listening socket and select an idle NVIDIA GPU before loading torch."""

import argparse
import csv
import io
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def query_gpu(fields: str, kind: str = "gpu") -> list[list[str]]:
    result = subprocess.run(
        ["nvidia-smi", f"--query-{kind}={fields}", "--format=csv,noheader,nounits"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    return list(csv.reader(io.StringIO(result.stdout), skipinitialspace=True))


def idle_gpu(max_memory: int, max_utilization: int) -> tuple[str, str, int]:
    busy = {row[0].strip() for row in query_gpu("gpu_uuid", "compute-apps") if row}
    candidates = []
    for row in query_gpu("index,uuid,memory.used,memory.free,utilization.gpu"):
        index, uuid, used, free, utilization = (item.strip() for item in row)
        try:
            used, free, utilization = int(used), int(free), int(utilization)
        except ValueError:
            continue  # Unknown utilization/memory is not evidence of an idle device.
        if uuid not in busy and used <= max_memory and utilization <= max_utilization:
            candidates.append((free, index, uuid))
    if not candidates:
        raise RuntimeError("没有空闲 GPU；请等待其他任务结束，或显式使用 --cpu")
    free, index, uuid = max(candidates)
    return index, uuid, free


def main() -> None:
    parser = argparse.ArgumentParser(description="自动选择空闲端口 / GPU，启动统一工作台")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=0, help="默认 0：由系统分配空闲端口")
    parser.add_argument("--cpu", action="store_true", help="显式使用 CPU，不检测 GPU")
    parser.add_argument("--dry-run", action="store_true", help="仅检查选择，不启动服务")
    parser.add_argument("--max-gpu-memory-mib", type=int, default=512)
    parser.add_argument("--max-gpu-utilization", type=int, default=5)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("端口范围必须是 0–65535")
    if args.max_gpu_memory_mib < 0 or not 0 <= args.max_gpu_utilization <= 100:
        parser.error("GPU 显存阈值必须非负，利用率阈值为 0–100")
    try:
        if args.cpu or shutil.which("nvidia-smi") is None:
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            os.environ["QUANT_TORCH_DEVICE"] = "cpu"
            device = "CPU（显式选择）" if args.cpu else "CPU（未检测到 NVIDIA GPU）"
        else:
            index, uuid, free = idle_gpu(args.max_gpu_memory_mib, args.max_gpu_utilization)
            os.environ["CUDA_VISIBLE_DEVICES"] = uuid
            os.environ["QUANT_TORCH_DEVICE"] = "cuda"
            device = f"GPU {index} · {uuid} · 空闲显存 {free} MiB"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            # Keep the socket open through startup: no check-then-bind port race.
            listener.bind((args.host, args.port))
            listener.listen(128)
            port = listener.getsockname()[1]
            print(f"计算设备：{device}", flush=True)
            print(f"监听地址：{args.host}:{port}", flush=True)
            print(f"工作台：http://127.0.0.1:{port}/research", flush=True)
            print("其他机器访问时，将 127.0.0.1 换为本机可达 IP。Ctrl+C 停止工作台。", flush=True)
            if args.dry_run:
                print("检查完成，未启动服务；端口已释放，下次启动可能不同。", flush=True)
                return
            if os.environ["QUANT_TORCH_DEVICE"] == "cuda":
                import torch

                if not torch.cuda.is_available():
                    raise RuntimeError("已选 GPU 无法初始化 CUDA，请检查驱动和 PyTorch 安装")
            import uvicorn

            os.environ["QUANT_FRONTEND_DIR"] = str(
                Path(__file__).resolve().parent.parent / "frontend/dist"
            )
            uvicorn.run("quant_workbench.api:app", fd=listener.fileno(), workers=1)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
