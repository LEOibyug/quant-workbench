"""Pre-registered, per-stock suitability diagnostic for a frozen daily strategy.

This is a research gate, not a promise of future returns.  Signals are read at
the close and applied to the next close-to-close return.  The final time block
is kept as an untouched confirmation block; no threshold is learned from it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig


BLOCK_DAYS = 126
MIN_DAYS = BLOCK_DAYS * 4
BOOTSTRAPS = 2000
SEED = 1729
FEE_BPS = 8.0  # round-trip conservative proxy for spread/slippage/fees


def _block_stats(returns: np.ndarray, block_days: int = BLOCK_DAYS) -> list[dict]:
    rows = []
    for start in range(0, len(returns), block_days):
        part = returns[start : start + block_days]
        if len(part) < block_days:
            break
        wealth = np.cumprod(1.0 + part)
        drawdown = wealth / np.maximum.accumulate(wealth) - 1.0
        rows.append(
            {
                "days": int(len(part)),
                "return_pct": float((wealth[-1] - 1.0) * 100.0),
                "max_drawdown_pct": float(drawdown.min() * 100.0),
                "positive_days_pct": float((part > 0).mean() * 100.0),
            }
        )
    return rows


def _bootstrap_lower(values: np.ndarray, seed: int = SEED) -> float:
    """One-sided 95% lower bound for the mean of independent time blocks."""
    if len(values) < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    sample = rng.choice(values, size=(BOOTSTRAPS, len(values)), replace=True).mean(axis=1)
    return float(np.quantile(sample, 0.05))


def evaluate(frame: pd.DataFrame, symbol: str, strategy: str = "fixed_ensemble") -> dict:
    required = {"day", "symbol", "open", "close"}
    if not required.issubset(frame.columns):
        return {"status": "证据不足", "reason": "行情字段不完整", "validated": False}
    frame = frame.copy()
    frame["day"] = frame["day"].astype(str)
    frame = frame.sort_values(["day", "symbol"])
    if symbol not in set(frame["symbol"]):
        return {"status": "证据不足", "reason": "股票缺少行情", "validated": False}
    # A frozen strategy is evaluated in its supplied universe.  This makes the
    # result explicitly conditional on the pool rather than a stock-intrinsic label.
    forecasts = rule_forecasts(frame, PositionConfig(model=strategy))
    rows = frame[frame["symbol"] == symbol].sort_values("day")
    days = rows["day"].to_numpy()
    close = rows["close"].to_numpy(dtype=float)
    signals = np.array([forecasts.get((str(d), symbol), {}).get("target_weight", 0.0) for d in days])
    if len(rows) < MIN_DAYS + 1:
        return {
            "status": "证据不足",
            "reason": f"共同策略历史至少需要{MIN_DAYS + 1}个交易日",
            "observations": int(len(rows)),
            "validated": False,
        }
    # Signal at t earns the following close-to-close move.  Turnover is charged
    # when the target changes, and the final position is liquidated at the end.
    price_returns = close[1:] / close[:-1] - 1.0
    held = signals[:-1]
    turnover = np.abs(np.diff(np.r_[0.0, held]))
    strategy_returns = held * price_returns - turnover * (FEE_BPS / 10000.0)
    strategy_returns[-1] -= abs(held[-1]) * (FEE_BPS / 10000.0)
    benchmark_returns = price_returns
    n = (len(strategy_returns) // BLOCK_DAYS) * BLOCK_DAYS
    strategy_returns = strategy_returns[-n:]
    benchmark_returns = benchmark_returns[-n:]
    strategy_blocks = _block_stats(strategy_returns)
    benchmark_blocks = _block_stats(benchmark_returns)
    excess = np.array(
        [a["return_pct"] - b["return_pct"] for a, b in zip(strategy_blocks, benchmark_blocks)]
    )
    confirmation = float(excess[-1])
    development = excess[:-1]
    lower = _bootstrap_lower(development)
    positive_fraction = float((development > 0).mean()) if len(development) else 0.0
    # These thresholds are fixed before inspecting a stock: at least three
    # development blocks, 75% positive, and a positive 5% lower bound, plus a
    # positive untouched confirmation block.
    candidate = bool(
        len(development) >= 3
        and positive_fraction >= 0.75
        and lower > 0.0
        and confirmation > 0.0
    )
    status = "候选适用（需独立确认）" if candidate else "未显示稳定优势"
    return {
        "status": status,
        "validated": False,
        "method": "frozen-strategy-walk-forward-v1",
        "symbol": symbol,
        "strategy": strategy,
        "universe": sorted(frame["symbol"].unique().tolist()),
        "observations": int(len(rows)),
        "block_days": BLOCK_DAYS,
        "fee_proxy_bps": FEE_BPS,
        "development": {
            "blocks": strategy_blocks[:-1],
            "benchmark_blocks": benchmark_blocks[:-1],
            "excess_return_pct": development.tolist(),
            "positive_block_fraction": positive_fraction,
            "bootstrap_mean_excess_lower_5pct": lower,
        },
        "confirmation": {
            "strategy_return_pct": strategy_blocks[-1]["return_pct"],
            "benchmark_return_pct": benchmark_blocks[-1]["return_pct"],
            "excess_return_pct": confirmation,
        },
        "reassess": "策略、股票池或费用假设变化后重新计算；新交易日滚动加入后再评估",
        "limitations": [
            "结果是给定策略和股票池下的条件判断，不是股票永久属性",
            "费用为保守代理，未替代完整成交模拟",
            "候选适用仍需另一时期/股票池的预先登记确认",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--strategy", default="fixed_ensemble")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(pd.read_parquet(args.prices), args.symbol.upper(), args.strategy)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()
