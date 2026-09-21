"""Point-in-time 10-Q income-change experiment, not earnings-announcement replication."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")
SEC = Path("artifacts/research/sec-quality")


def quarter_observations(facts):
    records = []
    for priority, tag in enumerate(["NetIncomeLoss", "ProfitLoss"]):
        for x in facts["facts"].get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", []):
            if x.get("form") not in ["10-Q", "10-Q/A"] or "start" not in x:
                continue
            duration = (date.fromisoformat(x["end"]) - date.fromisoformat(x["start"])).days
            if not 70 <= duration <= 110:
                continue
            records.append({**x, "tag": tag, "priority": priority})
    return records


def earnings_judge(records, day):
    visible = [r for r in records if r["filed"] < day and r["end"] < day]
    by_end = {}
    for r in sorted(
        visible, key=lambda x: (x["end"], -x["priority"], x["filed"], x.get("accn", ""))
    ):
        by_end[r["end"]] = r
    ends = sorted(by_end)
    differences = []
    for end in ends:
        previous = [
            p for p in ends if 330 <= (date.fromisoformat(end) - date.fromisoformat(p)).days <= 400
        ]
        if previous:
            prior = min(
                previous,
                key=lambda p: abs((date.fromisoformat(end) - date.fromisoformat(p)).days - 365),
            )
            differences.append((end, float(by_end[end]["val"] - by_end[prior]["val"])))
    if len(differences) < 9:
        return dict(status="证据不足", reason="不足8个历史同比差及当前差", signal=0.0)
    end, delta = differences[-1]
    row = by_end[end]
    first = min(r["filed"] for r in visible if r["end"] == end)
    age = (date.fromisoformat(day) - date.fromisoformat(end)).days
    std = float(np.std([v for _, v in differences[-9:-1]], ddof=1))
    if age > 200 or std <= 1e-8:
        return dict(status="证据不足", reason="季度陈旧或历史差分无有效尺度", signal=0.0)
    sue = delta / std
    return dict(
        status="候选通过" if sue > 0 and row["val"] > 0 else "候选未通过",
        signal=float(np.clip(sue / 2, 0, 1)) if row["val"] > 0 else 0.0,
        sue=sue,
        quarter_end=end,
        first_filed=first,
        source_filed=row["filed"],
        accn=row["accn"],
        tag=row["tag"],
        net_income=row["val"],
        delta=delta,
        scale=std,
    )


def forecasts(frame, with_price):
    prices = (
        frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    logs = np.log(prices.to_numpy())
    ret = np.diff(logs, axis=0)
    symbols = list(prices.columns)
    records = {
        s: quarter_observations(json.loads((SEC / f"{s}-facts.json").read_text())) for s in symbols
    }
    identities = json.loads((ROOT / "2026-09-21-sec-50-issuers.json").read_text())
    for symbol in symbols:
        if not identities[symbol]["identity_verified"]:
            records[symbol] = []
    sessions = list(
        schedule(
            str((pd.Timestamp(prices.index[0]) - pd.Timedelta(days=730)).date()),
            str((pd.Timestamp(prices.index[-1]) + pd.Timedelta(days=1)).date()),
        ).index.strftime("%Y-%m-%d")
    )
    import bisect

    out = {}
    counts = {"eligible": 0, "not_eligible": 0, "missing": 0, "expired": 0}
    examples = {}
    for i in range(126, len(prices)):
        day = str(prices.index[i])
        cov = LedoitWolf().fit(ret[i - 63 : i]).covariance_ + np.eye(len(symbols)) * 1e-12
        inv = 1 / np.sqrt(np.diag(cov))
        scores = []
        for j, s in enumerate(symbols):
            info = earnings_judge(records[s], day)
            score = info["signal"]
            if "first_filed" in info:
                elapsed = bisect.bisect_left(sessions, day) - bisect.bisect_right(
                    sessions, info["first_filed"]
                )
                if elapsed > 63:
                    score = 0.0
                    counts["expired"] += 1
                elif score > 0:
                    counts["eligible"] += 1
                else:
                    counts["not_eligible"] += 1
            else:
                counts["missing"] += 1
            if with_price:
                score *= max(
                    0, float(np.mean([np.sign(logs[i, j] - logs[i - k, j]) for k in (21, 63, 126)]))
                )
            scores.append(score)
            if s not in examples and day >= "2025-09-01":
                examples[s] = info
        weights = np.minimum(0.2, 0.95 * inv / inv.sum() * np.array(scores))
        weights *= min(1, 0.1 / max(float(np.sqrt(weights @ cov @ weights * 252)), 1e-12))
        for s, w in zip(symbols, weights, strict=True):
            out[(day, s)] = dict(target_weight=float(w), volatility=0.01, status="ok")
    return out, counts, examples


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    config = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    pools = {
        "original20": Repository().load_dataset(old["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    results = []
    dest = ROOT / "2026-09-21-filing-drift.json"
    for pool, frame in pools.items():
        for with_price in (False, True):
            mapping, coverage, examples = forecasts(frame, with_price)
            for mult in (1, 2):
                costs = dict(config["costs"])
                for k in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[k] *= mult
                cfg = PositionConfig(**{**config, "costs": costs})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    r = simulate_positions(frame, cfg, "2025-09-01", "2026-09-01", daily_bars=True)
                row = dict(
                    pool=pool,
                    with_price=with_price,
                    cost_multiplier=mult,
                    metrics=r["metrics"],
                    contributions=r["contributions"],
                    coverage=coverage,
                    initial_judgments=examples,
                    config=r["config"],
                )
                results.append(row)
                dest.write_text(
                    json.dumps(
                        dict(status="running", results=results), ensure_ascii=False, indent=2
                    )
                )
                print(
                    pool,
                    with_price,
                    mult,
                    round(r["metrics"]["return_pct"], 3),
                    round(r["metrics"]["max_drawdown_pct"], 3),
                    coverage,
                    flush=True,
                )
    dest.write_text(
        json.dumps(dict(status="completed", results=results), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
