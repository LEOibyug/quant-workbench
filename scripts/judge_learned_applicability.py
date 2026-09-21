"""Candidate probabilities, never an unsupported validated suitability claim."""

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from learned_applicability import CLASSES, feature, prepare


def judge(prices, symbol, date):
    result = dict(
        status="证据不足",
        method="learned-applicability-v0",
        symbol=symbol,
        as_of=date,
        reasons=[],
        validated=False,
    )
    if not {"day", "symbol", "close", "open"}.issubset(prices.columns):
        result["reasons"] = ["行情字段不完整"]
        return result
    frame = prices[prices.day.astype(str) <= date].copy()
    if symbol not in set(frame.symbol):
        result["reasons"] = ["股票缺少行情"]
        return result
    if date < "2025-09-01":
        result["reasons"] = ["该模型使用截至2025-08的数据，不能用于更早日期的事前判断"]
        return result
    try:
        close, _, weights = prepare(frame)
    except ValueError as error:
        result["reasons"] = [str(error)]
        return result
    if (pd.Timestamp(date) - pd.Timestamp(close.index[-1])).days > 7:
        result["reasons"] = ["最近行情距判断日期超过7日"]
        return result
    metadata = json.loads(
        Path("docs/research-results/2026-09-21-learned-applicability-training.json").read_text()
    )
    name = metadata["selected"]
    artifact = Path(f"artifacts/models/learned-applicability-v0/{name}.joblib")
    if (
        hashlib.sha256(artifact.read_bytes()).hexdigest()
        != metadata["models"][name]["artifact_sha256"]
    ):
        raise ValueError("Model hash mismatch")
    model = joblib.load(artifact)
    x = feature(
        np.log(close.to_numpy()), weights, len(close) - 1, list(close.columns).index(symbol)
    )
    p = np.zeros(4)
    p[model.classes_] = model.predict_proba(x[None])[0]
    result.update(
        model=name,
        signal_date=str(close.index[-1]),
        window_start=str(close.index[-64]),
        universe=list(close.columns),
        candidate_probabilities=dict(zip(CLASSES, p.tolist(), strict=True)),
        candidate_class=CLASSES[int(p.argmax())],
        reassess="每个新交易日收盘后重评；股票池变化时重算",
        reasons=[
            "概率为未经校准的分类输出，不是盈利概率",
            "尚无独立适用性确认；横截面专家依赖输入股票池",
        ],
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--prices", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            judge(
                pd.read_parquet(args.prices),
                args.symbol.upper(),
                pd.Timestamp(args.date).strftime("%Y-%m-%d"),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
