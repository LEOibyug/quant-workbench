"""Fixed aggregate trend/breadth exposure, no cross-sectional stock selection."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def forecasts(frame):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    values = p.to_numpy()
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Invalid prices")
    logs = np.diff(np.log(values), axis=0)
    market = np.r_[100.0, 100.0 * np.cumprod((values[1:] / values[:-1]).mean(axis=1))]
    maps = {m: {} for m in ("equal", "index_gate", "breadth")}
    diagnostic = []
    for i in range(199, len(p)):
        gate = float(market[i] > market[i - 199 : i + 1].mean())
        breadth = float(np.mean(values[i] > values[i - 199 : i + 1].mean(axis=0)))
        cov = LedoitWolf().fit(logs[i - 63 : i]).covariance_ + np.eye(p.shape[1]) * 1e-12
        base = np.full(p.shape[1], 0.95 / p.shape[1])
        base *= min(1, 0.1 / max(np.sqrt(base @ cov @ base * 252), 1e-12))
        for mode, scale in [("equal", 1.0), ("index_gate", gate), ("breadth", breadth)]:
            for j, s in enumerate(p.columns):
                maps[mode][str(p.index[i]), s] = dict(
                    target_weight=float(base[j] * scale),
                    volatility=float(np.sqrt(cov[j, j])),
                    status="ok",
                )
        if str(p.index[i]) >= "2025-09-01":
            diagnostic.append(dict(day=str(p.index[i]), index_gate=gate, breadth=breadth))
    return maps, diagnostic


def main():
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    rows = []
    diagnostics = {}
    destination = ROOT / "2026-09-21-pool-trend.json"
    for pool, meta in manifest.items():
        frame = pd.read_parquet(meta["path"])
        maps, diagnostic = forecasts(frame)
        diagnostics[pool] = diagnostic
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
                config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": 20})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    r = simulate_positions(
                        frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                    )
                rows.append(
                    dict(
                        pool=pool,
                        candidate=mode,
                        cost_multiplier=mult,
                        config=r["config"],
                        metrics=r["metrics"],
                        contributions=r["contributions"],
                        curve=r["curve"],
                    )
                )
                save_results(destination, rows)
                print(
                    pool,
                    mode,
                    mult,
                    r["metrics"]["return_pct"],
                    r["metrics"]["max_drawdown_pct"],
                    flush=True,
                )
    save_results(destination, rows, completed=True)
    (ROOT / "2026-09-21-pool-trend-states.json").write_text(json.dumps(diagnostics, indent=2))


if __name__ == "__main__":
    main()
