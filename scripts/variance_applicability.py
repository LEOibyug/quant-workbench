"""Heteroskedasticity-robust variance ratio; candidate state, not validated suitability."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def judge_returns(returns):
    r = np.asarray(returns, dtype=float)[-126:]
    result = dict(
        status="证据不足",
        method="variance_ratio_126_5_v0",
        candidate="cash",
        window_returns=len(r),
        threshold=1.96,
        validated=False,
    )
    if len(r) < 126 or not np.isfinite(r).all():
        return dict(**result, reason="需要126个连续有效日收益")
    q = 5
    n = len(r)
    e = r - r.mean()
    squares = e * e
    total = squares.sum()
    if total <= 1e-16:
        return dict(**result, reason="收益方差不足")
    aggregate = np.convolve(e, np.ones(q), mode="valid")
    vr = float((aggregate @ aggregate) / (q * (n - q + 1) * (1 - q / n)) / (total / (n - 1)))
    theta = sum(
        (2 * (q - j) / q) ** 2 * float(squares[j:] @ squares[:-j]) / (total * total)
        for j in range(1, q)
    )
    if theta <= 1e-16:
        return dict(**result, reason="检验渐近方差不足")
    z = float((vr - 1) / np.sqrt(theta))
    result.update(
        candidate="channel_trend" if z > 1.96 else ("residual_reversal" if z < -1.96 else "cash"),
        variance_ratio=vr,
        z=z,
        reason="仅收益相关性候选；策略净收益适用性尚未验证",
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    day = pd.Timestamp(args.date).strftime("%Y-%m-%d")
    f = pd.read_parquet(args.prices)
    g = f[(f.symbol == args.symbol.upper()) & (f.day <= day)].sort_values("day").tail(127)
    from quant_workbench.market_data import schedule

    if (
        len(g) < 127
        or g.day.duplicated().any()
        or list(g.day)
        != list(
            schedule(
                str(g.day.iloc[0]),
                (pd.Timestamp(g.day.iloc[-1]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            ).index.strftime("%Y-%m-%d")
        )
        or (g.close <= 0).any()
    ):
        result = dict(status="证据不足", candidate="cash", reason="价格缺少连续127个交易日")
    elif (pd.Timestamp(day) - pd.Timestamp(g.day.iloc[-1])).days > 7:
        result = dict(status="证据不足", candidate="cash", reason="最新价格距判断日超过7日")
    else:
        result = judge_returns(np.diff(np.log(g.close.to_numpy())))
        result.update(
            window_start=str(g.day.iloc[0]),
            signal_date=str(g.day.iloc[-1]),
            reassess="每个交易日收盘后；最早次日执行",
        )
    result.update(symbol=args.symbol.upper(), asof=day)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
