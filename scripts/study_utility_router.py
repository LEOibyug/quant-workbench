"""Compare frozen mean utility, conservative bootstrap and constant routing."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from learned_applicability import feature, prepare
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf
from study_covariance_allocation import save_results
from utility_router import choices, route_scores

ROOT = Path("docs/research-results")


def mappings(frame, bundle):
    close, _, expert_weights = prepare(frame)
    logs = np.log(close.to_numpy())
    returns = np.diff(logs, axis=0)
    x = np.array(
        [
            [feature(logs, expert_weights, i, j) for j in range(close.shape[1])]
            for i in range(63, len(close))
        ]
    )
    outputs = {m: {} for m in ("mean", "lower", "constant")}
    posterior = {
        m: np.eye(4)[choices(route_scores(bundle, x.reshape(-1, x.shape[-1]), m))].reshape(
            len(x), close.shape[1], 4
        )
        for m in outputs
    }
    diagnostics = {m: np.zeros(4) for m in outputs}
    observations = 0
    for i in range(63, len(close)):
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(close.shape[1]) * 1e-12
        if str(close.index[i]) >= "2025-09-01":
            observations += close.shape[1]
        for mode in outputs:
            mix = posterior[mode][i - 63]
            target = np.minimum(0.2, (mix[:, 1:] * expert_weights[i]).sum(axis=1))
            target *= min(
                1,
                0.95 / max(target.sum(), 1e-12),
                0.1 / max(np.sqrt(target @ cov @ target * 252), 1e-12),
            )
            for j, symbol in enumerate(close.columns):
                outputs[mode][str(close.index[i]), symbol] = dict(
                    target_weight=float(target[j]),
                    volatility=float(np.sqrt(cov[j, j])),
                    status="ok",
                )
            if str(close.index[i]) >= "2025-09-01":
                diagnostics[mode] += mix.sum(axis=0)
    return outputs, {m: (totals / observations).tolist() for m, totals in diagnostics.items()}


def main():
    artifact = Path("artifacts/models/utility-router-v0/model.joblib")
    training = json.loads((ROOT / "2026-09-21-utility-router-training.json").read_text())
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == training["artifact_sha256"]
    bundle = joblib.load(artifact)
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    results = []
    destination = ROOT / "2026-09-21-utility-router.json"
    for pool, meta in manifest.items():
        frame = pd.read_parquet(meta["path"])
        maps, diagnostics = mappings(frame, bundle)
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
                    r = simulate_positions(
                        frame, config, "2025-09-01", "2026-09-01", daily_bars=True
                    )
                results.append(
                    dict(
                        pool=pool,
                        candidate=mode,
                        cost_multiplier=mult,
                        choice_fractions=diagnostics[mode],
                        config=r["config"],
                        metrics=r["metrics"],
                        contributions=r["contributions"],
                        curve=r["curve"],
                    )
                )
                save_results(destination, results)
                print(
                    pool,
                    mode,
                    mult,
                    r["metrics"]["return_pct"],
                    r["metrics"]["max_drawdown_pct"],
                    flush=True,
                )
    save_results(destination, results, completed=True)


if __name__ == "__main__":
    main()
