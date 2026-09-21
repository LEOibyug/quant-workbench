"""Withdrawn suitability gate; fail closed until a valid protocol is implemented."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig


def evaluate(frame: pd.DataFrame, symbol: str, strategy: str = "fixed_ensemble") -> dict:
    return {
        "status": "证据不足",
        "validated": False,
        "method": "frozen-strategy-walk-forward-v1-withdrawn",
        "symbol": symbol,
        "strategy": strategy,
        "reason": "旧判定方法已撤回，不能根据其输出选择股票",
        "limitations": [
            "小比例组合贡献与满仓买入持有不可直接比较",
            "收盘信号按同一收盘价成交不符合下一开盘执行约束",
            "历史末块已在研究中使用，不能视为未触碰确认集",
            "少量区块bootstrap不能证明适用性，且未校正多股票筛选",
            "缺少公司行动、共同交易日及风险匹配核验",
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
