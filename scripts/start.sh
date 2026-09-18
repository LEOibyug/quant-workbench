#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "用法：./scripts/start.sh [--host 0.0.0.0] [--port 0] [--cpu] [--dry-run]"
  echo "安装依赖并构建网页，自动选择空闲端口 / GPU；单个进程提供网页和计算。"
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
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
exec uv run --locked --extra neural python scripts/start.py "$@"
