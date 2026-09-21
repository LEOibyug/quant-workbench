"""Frozen statistical state gating versus unconditional and exposure controls."""

import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results
from variance_applicability import judge_returns

ROOT = Path("docs/research-results")


def forecasts(frame):
    close = (
        frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    returns = np.diff(np.log(close.to_numpy()), axis=0)
    experts = {
        name: rule_forecasts(frame, PositionConfig(model=name))
        for name in ("channel_trend", "residual_reversal")
    }
    out = {m: {} for m in ("vr_router", "ungated", "gross_equal")}
    counts = Counter()
    for i in range(126, len(close)):
        day = str(close.index[i])
        judgment = [judge_returns(returns[i - 126 : i, j]) for j in range(close.shape[1])]
        if day >= "2025-09-01":
            counts.update(r["candidate"] for r in judgment)
        w = np.array(
            [
                experts.get(judgment[j]["candidate"], {})
                .get((day, s), {})
                .get("target_weight", 0.0)
                for j, s in enumerate(close.columns)
            ]
        )
        ungated = np.array(
            [sum(m[(day, s)]["target_weight"] for m in experts.values()) / 2 for s in close.columns]
        )
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(close.shape[1]) * 1e-12
        targets = {}
        for mode, target in [("vr_router", w), ("ungated", ungated)]:
            target = np.minimum(0.2, target)
            target *= min(
                1,
                0.95 / max(target.sum(), 1e-12),
                0.1 / max(np.sqrt(target @ cov @ target * 252), 1e-12),
            )
            targets[mode] = target
        targets["gross_equal"] = np.full(
            close.shape[1], targets["vr_router"].sum() / close.shape[1]
        )
        for mode, target in targets.items():
            for j, s in enumerate(close.columns):
                out[mode][day, s] = dict(
                    target_weight=float(target[j]),
                    volatility=float(np.sqrt(cov[j, j])),
                    status="ok",
                )
    return out, dict(counts)


def main():
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    rows = []
    output = ROOT / "2026-09-21-variance-router.json"
    for pool, meta in manifest.items():
        f = pd.read_parquet(meta["path"])
        maps, counts = forecasts(f)
        for mode, mapping in maps.items():
            for mult in (1, 2):
                costs = dict(cfg["costs"])
                for key in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[key] *= mult
                config = PositionConfig(**{**cfg, "costs": costs})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    r = simulate_positions(f, config, "2025-09-01", "2026-09-01", daily_bars=True)
                rows.append(
                    dict(
                        pool=pool,
                        candidate=mode,
                        cost_multiplier=mult,
                        classification_counts=counts,
                        config=r["config"],
                        metrics=r["metrics"],
                        contributions=r["contributions"],
                        curve=r["curve"],
                    )
                )
                save_results(output, rows)
                print(
                    pool,
                    mode,
                    mult,
                    r["metrics"]["return_pct"],
                    r["metrics"]["max_drawdown_pct"],
                    flush=True,
                )
    save_results(output, rows, completed=True)


if __name__ == "__main__":
    main()
