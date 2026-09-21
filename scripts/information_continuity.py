"""Conditional price-path continuity; research conditions, not validated suitability."""

import argparse
import json

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf


def path_metrics(log_returns):
    r = np.asarray(log_returns, dtype=float)
    if r.ndim != 2 or not len(r) or not np.isfinite(r).all():
        raise ValueError("Need a finite days-by-symbols return matrix")
    pret = r.sum(axis=0)
    # Price scaling can perturb exact zero differences at floating-point precision.
    signs = np.where(np.abs(r) <= 1e-12, 0, np.sign(r))
    identity = np.sign(pret) * -signs.mean(axis=0)
    return pret, identity


def forecasts(frame, start, end):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    values = p.to_numpy()
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Incomplete or nonpositive prices")
    logs = np.log(values)
    returns = np.diff(logs, axis=0)
    syms = list(p.columns)
    days = [str(d) for d in p.index if start <= str(d) < end]
    decisions = set(days[::20])
    maps = {m: {} for m in ("continuous", "discrete", "eligible")}
    diagnostics = []
    for i, day in enumerate(p.index):
        day = str(day)
        if day not in decisions:
            continue
        if i < 252:
            raise ValueError(f"Insufficient formation history at {day}")
        pret, identity = path_metrics(returns[i - 252 : i - 21])
        winners = sorted(
            (j for j in range(len(syms)) if pret[j] > 0), key=lambda j: (pret[j], syms[j])
        )
        groups = {k: [] for k in maps}
        pairs = []
        for a, b in zip(winners[::2], winners[1::2], strict=False):
            # Counts/231 have exact ties; do not use alphabet to allocate tied ID.
            if identity[a] == identity[b]:
                continue
            low, high = sorted((a, b), key=lambda j: identity[j])
            groups["continuous"].append(low)
            groups["discrete"].append(high)
            groups["eligible"].extend((a, b))
            pairs.append(
                dict(
                    continuous=syms[low],
                    discrete=syms[high],
                    pret_gap=float(abs(pret[a] - pret[b])),
                )
            )
        budget = min(0.95, 0.2 * len(pairs))
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(len(syms)) * 1e-12
        vol = np.sqrt(np.diag(cov))
        for method, selected in groups.items():
            raw = np.array([1 / vol[j] if j in selected else 0 for j in range(len(syms))])
            w = np.minimum(0.2, budget * raw / max(raw.sum(), 1e-12))
            w *= min(1, 0.1 / max(np.sqrt(w @ cov @ w * 252), 1e-12))
            for j, s in enumerate(syms):
                maps[method][day, s] = dict(
                    target_weight=float(w[j]), volatility=float(vol[j]), status="ok"
                )
        diagnostics.append(
            dict(
                day=day,
                formation_start=str(p.index[i - 252]),
                formation_end=str(p.index[i - 21]),
                return_observations=231,
                budget=budget,
                pairs=pairs,
                eligible=[syms[j] for j in groups["eligible"]],
                selected={m: [syms[j] for j in chosen] for m, chosen in groups.items()},
                judgments={
                    s: dict(
                        pret_log=float(pret[j]),
                        information_discreteness=float(identity[j]),
                        status="证据不足",
                        positive_momentum=bool(pret[j] > 0),
                    )
                    for j, s in enumerate(syms)
                },
            )
        )
    return maps, diagnostics, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--date", required=True, help="Use only completed sessions strictly before this date"
    )
    args = parser.parse_args()
    day = pd.Timestamp(args.date).date().isoformat()
    frame = pd.read_parquet(args.prices)
    frame = frame[frame.day < day]
    symbol = args.symbol.upper()
    result = dict(
        symbol=symbol,
        asof=day,
        status="证据不足",
        validated=False,
        strategy="conditional-information-continuity-v1",
    )
    if symbol not in set(frame.symbol) or frame.day.nunique() < 253:
        result["reason"] = "股票缺失或不足253个完整交易日"
    else:
        last = str(frame.day.max())
        if (pd.Timestamp(day) - pd.Timestamp(last)).days > 7:
            result["reason"] = "行情陈旧，拒绝当前判断"
        else:
            _, ds, _ = forecasts(frame, last, day)
            d = ds[0]
            result.update(d["judgments"][symbol])
            result.update(
                signal_day=last,
                formation_start=d["formation_start"],
                formation_end=d["formation_end"],
                candidate_pass=symbol in d["selected"]["continuous"],
                pair=next(
                    (p for p in d["pairs"] if symbol in (p["continuous"], p["discrete"])), None
                ),
                pool=sorted(frame.symbol.unique()),
                reason="配对内较低ID仅为候选条件；未确认净收益判别能力",
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
