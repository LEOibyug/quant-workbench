"""Inspectable marginal-model output, always unconfirmed suitability."""

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from learned_applicability import prepare
from quant_workbench.conditional_policy import decompose
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig
from sklearn.covariance import LedoitWolf


def judge(frame, symbol, date):
    date = pd.Timestamp(date).strftime("%Y-%m-%d")
    symbol = symbol.strip().upper()
    result = dict(
        symbol=symbol, asof=date, status="证据不足", method="marginal-model-v0", validated=False
    )
    if date < "2025-09-01":
        return dict(**result, reason="该版本训练与检查使用2025-09之前数据，不能用于更早的事前判断")
    required = {"day", "symbol", "open", "close"}
    if not required.issubset(frame.columns):
        return dict(**result, reason="缺少行情字段")
    f = frame[frame.day.astype(str) <= date]
    if symbol not in set(f.symbol):
        return dict(**result, reason="缺少股票行情")
    try:
        close, _, _ = prepare(f)
    except ValueError as error:
        return dict(**result, reason=str(error))
    if (pd.Timestamp(date) - pd.Timestamp(close.index[-1])).days > 7:
        return dict(**result, reason="最近行情陈旧超过7日")
    f = f[f.day.isin(close.index)]
    symbols = list(close.columns)
    j = symbols.index(symbol)
    logs = np.log(close.to_numpy())
    returns = np.diff(logs, axis=0)[-63:]
    cov = LedoitWolf().fit(returns).covariance_ + np.eye(len(symbols)) * 1e-12
    market = returns.mean(axis=1)
    m = market - market.mean()
    beta = (returns - returns.mean(axis=0)).T @ m / max(m @ m, 1e-15)
    old = json.loads(Path("docs/research-results/2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    mapping = rule_forecasts(f, PositionConfig(**cfg))
    day = str(close.index[-1])
    w = np.array([mapping[day, s]["target_weight"] for s in symbols])
    x = np.r_[decompose(logs[-64:, j])[1], w[j], w.sum(), np.sqrt(cov[j, j]), beta[j]]
    path = Path("artifacts/models/marginal-model-v0/model.joblib")
    meta = Path("docs/research-results/2026-09-21-marginal-model-training.json")
    if not path.exists() or not meta.exists():
        return dict(**result, reason="模型尚未训练完成")
    if (
        hashlib.sha256(path.read_bytes()).hexdigest()
        != json.loads(meta.read_text())["artifact_sha256"]
    ):
        raise ValueError("Artifact hash mismatch")
    value = float(joblib.load(path).predict(x[None])[0])
    return dict(
        **result,
        signal_date=day,
        universe=symbols,
        estimated_marginal_utility_pp=value,
        candidate_positive=value > 0,
        current_target_weight=float(w[j]),
        reason="未验证的回归输出，不是盈利概率；标签假设从现金开始部署，不适用于已有持仓状态",
        reassess="每个新交易日收盘后或股票池变化后重算",
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--prices", type=Path, required=True)
    a = p.parse_args()
    print(
        json.dumps(judge(pd.read_parquet(a.prices), a.symbol, a.date), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
