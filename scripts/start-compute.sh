#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if ! command -v uv >/dev/null 2>&1; then
  echo "请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
exec uv run --locked --extra neural python scripts/start_compute.py "$@"
