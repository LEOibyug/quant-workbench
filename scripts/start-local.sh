#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "用法：./scripts/start-local.sh [--api-port 8000] [--web-port 5173]"
  echo "安装轻量依赖并启动本地网关与网页；监听 127.0.0.1，Ctrl+C 一起停止。"
  exit 0
fi
for tool in uv node npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "缺少 $tool，请安装 uv 和 Node.js 22.12+ 或 24。" >&2
    exit 1
  fi
done
node --input-type=module -e '
const [major, minor] = process.versions.node.split(".").map(Number);
if (!((major === 22 && minor >= 12) || major === 24)) {
  console.error("需要 Node.js 22.12+（22.x）或 24.x"); process.exit(1);
}'
if [[ ! -x .venv-local/bin/python ]]; then
  uv venv .venv-local --python 3.12
fi
uv pip install --python .venv-local/bin/python -r requirements-local.txt
# npm ci follows the lockfile and does not change project dependencies.
npm --prefix frontend ci --no-audit --no-fund
exec .venv-local/bin/python scripts/start_local.py "$@"
