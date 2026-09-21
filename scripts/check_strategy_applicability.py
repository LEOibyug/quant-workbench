"""Explain a research candidate's conditions without claiming validated suitability."""

import argparse
import json
from pathlib import Path

import pandas as pd
from study_state_gate import SEC, judge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument(
        "--prices", type=Path, required=True, help="Daily parquet with symbol/day/OHLCV"
    )
    parser.add_argument("--price-only", action="store_true")
    args = parser.parse_args()
    asof = pd.Timestamp(args.date).strftime("%Y-%m-%d")
    symbol = args.symbol.strip().upper()
    frame = pd.read_parquet(args.prices)
    if not {"symbol", "day", "close", "volume"}.issubset(frame.columns):
        raise ValueError("日线字段不完整")
    rows = frame[frame.symbol == symbol]
    facts_path = SEC / f"{symbol}-facts.json"
    sub_path = SEC / f"{symbol}-submission.json"
    facts = json.loads(facts_path.read_text()) if facts_path.exists() else None
    sub = json.loads(sub_path.read_text()) if sub_path.exists() else None
    result = judge(rows, asof, facts, sub, not args.price_only)
    result["symbol"] = symbol
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
