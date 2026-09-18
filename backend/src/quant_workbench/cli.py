"""Portable diagnostic and planning commands; no automatic GPU installation."""

import argparse
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

from quant_workbench.storage import estimate_storage


def main() -> None:
    parser = argparse.ArgumentParser(description="Local quant workbench tools")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, default_port in (("serve-local", 8000), ("serve-compute", 8001)):
        serve = sub.add_parser(name, help="Start independent local gateway or compute service")
        serve.add_argument("--host", default="127.0.0.1")
        serve.add_argument("--port", type=int, default=default_port)
    sub.add_parser("doctor", help="Report environment without loading optional GPU packages")
    estimate = sub.add_parser("estimate", help="Estimate compressed OHLCV storage")
    estimate.add_argument("--symbols", type=int, default=7)
    estimate.add_argument("--years", type=float, default=2)
    estimate.add_argument("--interval-seconds", type=int, default=60)
    study = sub.add_parser("study", help="Train-only diagnostics and cost-aware validation search")
    study.add_argument("--dataset", required=True)
    for name in ("start", "train-end", "validation-end", "end"):
        study.add_argument("--" + name, required=True)
    study.add_argument("--symbols", nargs="+")
    study.add_argument("--output")
    study.add_argument("--include-test", action="store_true")
    study.add_argument("--suite", choices=["legacy", "enhanced", "sequence"], default="legacy")
    args = parser.parse_args()
    if args.command in {"serve-local", "serve-compute"}:
        import uvicorn

        module = "local_api" if args.command == "serve-local" else "compute_api"
        uvicorn.run(f"quant_workbench.{module}:app", host=args.host, port=args.port, workers=1)
        return
    if args.command == "study":
        from quant_workbench.repository import Repository
        from quant_workbench.study import run_study

        output = run_study(
            Repository(),
            args.dataset,
            args.start,
            args.train_end,
            args.validation_end,
            args.end,
            args.symbols,
            args.output,
            args.include_test,
            suite=args.suite,
        )
        print(output / "report.md")
        return
    if args.command == "doctor":
        data_dir = Path(os.environ.get("QUANT_DATA_DIR", "data")).expanduser().resolve()
        existing = data_dir
        while not existing.exists():
            existing = existing.parent
        result = {
            "python": platform.python_version(),
            "executable": sys.executable,
            "os": platform.system(),
            "architecture": platform.machine(),
            "data_directory": str(data_dir),
            "disk_free_gib": round(shutil.disk_usage(existing).free / 2**30, 2),
            "default_compute": "rules/legacy: cpu; GRU: auto cuda > cpu (MPS dropped)",
            "nvidia_smi_on_path": shutil.which("nvidia-smi") is not None,
            "gpu_note": "GRU requires neural extra; QUANT_TORCH_DEVICE=auto/cuda/cpu. "
            "CUDA path enables cudnn autotuning and TF32 matmul. "
            "Executable presence alone does not establish CUDA availability.",
        }
    else:
        try:
            result = asdict(
                estimate_storage(args.symbols, args.years, interval_seconds=args.interval_seconds)
            )
        except ValueError as exc:
            parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
