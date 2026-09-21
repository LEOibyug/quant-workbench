"""Fixed 55%-variance PCA residual candidate, not a full paper replication."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import study_symmetric_trend as ledger
from sklearn.covariance import LedoitWolf
from study_factor_ou import hedge, residual_scores

ROOT = Path("docs/research-results")


def factors_and_scores(history):
    scale = np.maximum(history.std(axis=0, ddof=1), 1e-8)
    z = (history - history.mean(axis=0)) / scale
    corr = z.T @ z / (len(z) - 1)
    values, vectors = np.linalg.eigh(corr)
    order = np.argsort(values)[::-1]
    values = np.maximum(values[order], 0)
    if values.sum() <= 1e-12:
        return np.full(history.shape[1], np.nan), np.zeros((history.shape[1], 1)), 0
    count = int(np.searchsorted(np.cumsum(values) / values.sum(), 0.55) + 1)
    factors = z[-60:] @ vectors[:, order[:count]]
    scores, beta = residual_scores(history[-60:], factors)
    return scores, beta, count


def neutralize(weights, beta):
    return weights - beta @ np.linalg.pinv(beta) @ weights


def forecasts(frame):
    p = frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    returns = np.diff(np.log(p.to_numpy()), axis=0)
    state = np.zeros(p.shape[1])
    output = {m: {} for m in ("long_only", "signed", "pca_hedged")}
    diagnostics = []
    for i in range(252, len(p)):
        history = returns[i - 252 : i]
        if not np.isfinite(history).all():
            raise ValueError("Incomplete history")
        scores, beta, count = factors_and_scores(history)
        for j, s in enumerate(scores):
            if not np.isfinite(s):
                state[j] = 0
            elif state[j] > 0:
                if s > -0.5:
                    state[j] = 0
            elif state[j] < 0:
                if s < 0.75:
                    state[j] = 0
            elif s < -1.25:
                state[j] = 1
            elif s > 1.25:
                state[j] = -1
        cov = LedoitWolf().fit(history[-60:]).covariance_ + np.eye(p.shape[1]) * 1e-12
        inv = 1 / np.sqrt(np.diag(cov))
        raw = 0.95 * inv / inv.sum() * state
        neutral = hedge(neutralize(raw, beta), np.zeros(p.shape[1]), cov, "signed")
        for mode in output:
            target = (
                neutral if mode == "pca_hedged" else hedge(raw, np.zeros(p.shape[1]), cov, mode)
            )
            output[mode][str(p.index[i])] = dict(zip(p.columns, target.tolist(), strict=True))
        diagnostics.append(
            dict(
                day=str(p.index[i]),
                factors=count,
                valid=int(np.isfinite(scores).sum()),
                active=int(np.count_nonzero(state)),
                hedge_error=float(np.max(np.abs(neutral @ beta))),
            )
        )
    return output, diagnostics


def main():
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    results = []
    diagnostics = {}
    output = ROOT / "2026-09-21-pca-ou.json"
    for pool, meta in manifest.items():
        frame = pd.read_parquet(meta["path"])
        maps, diagnostic = forecasts(frame)
        diagnostics[pool] = diagnostic
        for mode, mapping in maps.items():
            for mult in (1, 2):
                with patch("study_symmetric_trend.forecasts", return_value=mapping):
                    r = ledger.simulate(frame, mode, mult, rebalance_days=1)
                r.update(pool=pool, candidate="pca_ou_55_v0", rebalance_days=1)
                results.append(r)
                output.write_text(
                    json.dumps(
                        dict(status="running", results=results, diagnostics=diagnostics), indent=2
                    )
                )
                print(pool, mode, mult, r["return_pct"], r["max_drawdown_pct"], flush=True)
    output.write_text(
        json.dumps(dict(status="completed", results=results, diagnostics=diagnostics), indent=2)
    )


if __name__ == "__main__":
    main()
