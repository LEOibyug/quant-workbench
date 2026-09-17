# Local Quant Workbench Foundation Implementation Plan

> **For agentic workers:** Execute inline using superpowers:executing-plans. 本轮用户已授权当前目录初始化、建立venv、维护Git并推送GitHub。

**Goal:** Create a reproducible local development foundation with storage budgeting and GitHub delivery.

**Architecture:** Frontend and Python API run as native local processes. Research and workspace are separate routes. CPU is the default; optional GPU frameworks are installed per server and never imported by the base application.

**Tech Stack:** Python 3.12, uv lock, FastAPI, NumPy/Pandas/PyArrow/DuckDB, React/TypeScript/Vite, npm lock, GitHub Actions.

**Spec:** `需求/本地美股策略平台范围与课件分析.md` plus user acceptance on 2026-09-17. This plan delivers the requested environment/repository milestone, not the full trading product.

## Global Constraints

- Work in the current project directory; no containers or linked worktrees required.
- Python >=3.12,<3.13; Node.js 22 or24.
- macOS arm64 and Linux x86_64 CPU path must share the same source and lockfile.
- GPU optional, no CUDA dependency in the base environment.
- Do not upload references, raw data, credentials, environments or experiment artifacts.
- GitHub repository private by default, no force pushes.

## Task 1 Reproducible environment

- [x] Create `.gitignore`, `.python-version`, `pyproject.toml`, `README.md`.
- [x] Run `uv venv --python 3.12 .venv`, then `uv lock` and `uv sync --locked`.
- [x] Verify `uv run python --version` and import FastAPI/NumPy/Pandas/PyArrow/DuckDB.

## Task 2 Storage and platform diagnostics

Files: `backend/src/quant_workbench/{storage,cli,api}.py`, `tests/test_storage.py`, `tests/test_api.py`.

Interfaces: `estimate_storage(symbols=7, years=2, days_per_year=252, minutes_per_day=390)` returns row count, compressed-byte range, working-copy range. API provides `/api/health`, `/api/storage-estimate`; CLI provides `doctor` and `estimate`.

- [x] Write tests requiring `7*2*252*390 == 1375920`, zero/negative/nonfinite input rejection, and immutable estimate assumptions.
- [x] Run `uv run pytest` and observe missing implementation failures.
- [x] Implement calculation with stated 24—64 compressed bytes/row and 3× working-copy reserve; no market data download.
- [x] Add structured runtime diagnostics: OS, architecture, Python, configured local data path, free disk, optional `nvidia-smi` availability without importing CUDA.
- [x] API test status, estimate and invalid input; rerun tests and lint.

## Task 3 Separate frontend panels

Files: `frontend/{package.json,package-lock.json,tsconfig.json,index.html,vite.config.ts,src/*}`.

- [x] Create two routes `/research` and `/workspace`, API connectivity indicator and estimate form.
- [x] Clearly mark market ingestion/backtest/live trading as unimplemented; never show synthetic returns as actual results.
- [x] Run `npm ci`, `npm run build` and browser smoke checks on both routes.

## Task 4 Storage evidence and portability

Files: `docs/{storage-estimate,setup}.md`, `.github/workflows/ci.yml`, `scripts/benchmark_storage.py`.

- [x] Generate a deterministic synthetic 7-symbol 2-year minute dataset solely to measure Parquet footprint; mark the result synthetic.
- [x] Report minute/second/trade/quote estimates separately with explicit assumptions; disclose tick-rate uncertainty and exclude vendor compressed-download size claims.
- [x] Document Linux CPU setup, optional isolated GPU environment and driver-specific installation selection; do not claim GPU acceleration for sequential backtesting.
- [x] Configure macOS and Ubuntu CPU CI plus frontend build.

## Task 5 Git and remote delivery

- [x] Initialize local Git, review staged file list and verify excluded materials with `git check-ignore`.
- [x] Run tests, lint, build and dependency sync verification; commit only project source and textual planning docs.
- [x] Create `LEOibyug/quant-workbench` private via `gh repo create --private --source . --remote origin --push`.
- [x] Verify remote URL, visibility, matching commit and CI outcome. Report failures truthfully and fix compatibility failures when reproducible.

## Verification record

Local: 16 pytest cases passed, Ruff passed, uv dependency check passed, clean npm install and frontend build passed. Browser checked both routes, API connection and estimate update. GitHub Actions run 35220404787 completed successfully for the initial source commit, including macOS/Linux CPU and Node22/24. NVIDIA hardware execution remains unverified.
