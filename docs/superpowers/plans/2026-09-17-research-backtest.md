# Historical Research MVP Implementation Plan

> **For agentic workers:** Execute using superpowers:executing-plans; request an independent review with superpowers:requesting-code-review before release.

**Goal:** Deliver local data import, frozen experiment definitions, chronological evaluation, cost-aware backtesting and usable research/results panels.

**Architecture:** FastAPI receives CSV uploads or retrieves authenticated Alpaca or Massive historical bars. Immutable Parquet datasets and a local SQLite catalog hold provenance and experiments. A deterministic CPU event simulation consumes completed one-minute bars; React displays persistent results.

**Tech Stack:** Existing Python3.12/FastAPI/Pandas/PyArrow, exchange-calendars, httpx, python-multipart; React/TypeScript/Vite.

**Spec:** `需求/本地美股策略平台范围与课件分析.md`, accepted user defaults and instruction “开始实现”.

## Global Constraints

- Native local deployment, no containers; portable Mac/Linux paths.
- No live trading; no API credentials transmitted to frontend or stored in experiment metadata.
- Only regular-session US stocks, 1-minute completed bars, integer long shares, no leverage.
- Frozen dataset and parameters; train/validation/test chronological, disjoint date intervals.
- Final evaluation requires validation; repeated identical requests return stored results. Prior test exposure across experiments is disclosed, not falsely protected by a frontend toggle.
- Synthetic demo always labelled; actual provider connection must not be claimed without real fetch.
- Bar simulation is approximate, not tick/queue-accurate execution. Costs and assumptions appear with results.

## 1 Data contracts and persistence

Files: `backend/src/quant_workbench/{models,data,repository,providers}.py`; tests for dataset validation and API persistence.

- [x] Add validated dataset and experiment schemas. CSV timestamp requires explicit timezone and denotes minute end. Provider minute-start bars shift +1 minute.
- [x] Test duplicate, nonfinite/invalid OHLC, naive time and off-session rejection; validate XNYS calendar, DST and early closes.
- [x] Save normalized Parquet atomically; persist SHA256, source, synthetic marker, coverage and symbols in SQLite under QUANT_DATA_DIR.
- [x] Implement Alpaca pagination using env keys, fixed URL/feed, maximum records and sanitized errors. Reject incomplete responses when capped.
- [x] Generate an explicitly synthetic demo with full sessions across at least30 trading days, no external network.

## 2 Causal simulation

Files: `engine.py`, `metrics.py`, `tests/test_engine.py`.

- [x] Write hand-computed tests for next-bar execution, fees, cash, end-of-day flattening, signal invariance to future prices and constant-price loss after costs.
- [x] Implement per-symbol cash sleeves; completed-bar rolling SMA; target long when fast>slow, next-bar open fills plus1second nominal latency; spread half-cost and additional slippage per side.
- [x] Require complete synchronized regular sessions for the selected symbols; reject missing bars rather than fabricate fills or liquidation.
- [x] Position size uses available cash including minimum/per-share commission and per-sale fee. Apply participation cap; latch exits until flat and carry current entry target, no duplicate order accumulation.
- [x] Schedule flattening from exchange close, independent of dataset end; if volume constraints prevent closing, fail rather than silently pretend flat.
- [x] Emit daily-marked equity, trade log, cost breakdown, per-symbol contribution, daily-return Sharpe, drawdown and same-symbol daily open-to-close benchmark with explicit assumptions.

## 3 Experiment service

Files: `research.py`, `research_api.py`, `tests/test_research.py`.

- [x] Test date ordering, full coverage, frozen parameters, validation prerequisite, final replay and exposure flags on overlapping test dates.
- [x] Persist experiments and each phase result; prevent concurrent duplicate phase execution using transactional running state.
- [x] Run phase in thread-backed background job with status polling; recover interrupted running jobs on startup. Bound worker concurrency and input size.
- [x] API endpoints: datasets list/import/demo/Alpaca; experiments create/list; phase run/status/result. Result detail caps large trade/curve payloads; CSV export full records.

## 4 Frontend

Files: `frontend/src/{main,api,types,Research,Workspace,Results}.tsx/ts`, CSS.

- [x] Research: dataset import and selection; exact split dates; parameters/cost controls; create immutable experiment; run phases with validation gate and progress/error states.
- [x] Workspace: select experiment/phase, equity and drawdown, cost/return metrics, trade list and CSV export; synthetic warning and execution assumptions visible.
- [x] Show honest empty states, no invented market returns. Verify browser flow with demo then malformed import.

## 5 Delivery

- [x] Run Python tests, lint, frontend build and browser end-to-end checks; independent code review completed, focused on financial correctness and data leakage.
- [x] Document API/data format, cost model, data completeness requirement, limitations and startup commands.
- [x] Commit and push GitHub branch; fast-forward main after independent review and local checks. GitHub cross-platform checks run after push. No paid subscriptions or actual orders.


## Online model extension accepted during implementation

- [x] Offline SGD probability classifier, frozen scaler, causal k-window features and matured one-minute labels.
- [x] First 2k observations prohibit entries; k..2k adaptation followed by continuous per-symbol online learning.
- [x] Each phase reloads the same offline artifact; separate online checkpoints; accuracy, Brier, log-loss and fixed train-frequency baseline.
- [x] Review fixes: persistent partial exits, split-neutral intraday benchmark and configurable five-minute flattening.
- [x] Native API provider workflow primary; CSV remains optional. Real account verification awaits local credentials.

Local release validation: 42 tests, Ruff, TypeScript/Vite build; browser tested provider selection and missing-key error, frozen five-symbol demo, validation gate, completed validation/test and result charts. Malformed CSV and HTTP contracts tested through the API. GitHub CI status recorded separately at delivery; live market and NVIDIA testing not performed.
