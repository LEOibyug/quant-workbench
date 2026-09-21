"""Enumerate whole-trajectory identity permutations; descriptive, not an exact p-test."""

import gzip
import itertools
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from quant_workbench.position import PositionConfig, simulate_positions
from sklearn.covariance import LedoitWolf

ROOT = Path("docs/research-results")
SYMBOLS = ["ACN", "GILD", "INTU", "NKE"]


def prepare(frame, coverage):
    close = (
        frame.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    returns = np.diff(np.log(close.to_numpy()), axis=0)
    prepared = []
    for d in coverage:
        assert set(d["eligible"]) == set(SYMBOLS)
        i = close.index.get_loc(d["day"])
        assert i >= 63
        cov = LedoitWolf().fit(returns[i - 63 : i]).covariance_ + np.eye(len(close.columns)) * 1e-12
        prepared.append((d, cov, np.sqrt(np.diag(cov))))
    return list(close.columns), prepared


def mapping_for(syms, prepared, permutation):
    rename = dict(zip(SYMBOLS, permutation, strict=True))
    mapping = {}
    for d, cov, vol in prepared:
        selected = {rename[s] for s in d["selected"]["nonincrease"]}
        assert len(selected) == len(d["selected"]["nonincrease"])
        raw = np.array([1 / vol[j] if s in selected else 0 for j, s in enumerate(syms)])
        w = np.minimum(0.2, d["budget"] * raw / max(raw.sum(), 1e-12))
        w *= min(1, 0.1 / max(np.sqrt(w @ cov @ w * 252), 1e-12))
        for j, s in enumerate(syms):
            mapping[d["day"], s] = dict(
                target_weight=float(w[j]), volatility=float(vol[j]), status="ok"
            )
    return mapping


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    recent = json.loads((ROOT / "2026-09-21-receivables-strategy-coverage.json").read_text())[
        "random10"
    ]["coverage"]
    temporal = next(
        r["coverage"]
        for r in json.loads((ROOT / "2026-09-21-receivables-temporal-coverage.json").read_text())
        if r["start"] == "2022-09-01" and r["end"] == "2025-09-01"
    )
    rows = []
    full = []
    dest = ROOT / "2026-09-21-receivables-permutation.json"
    for start, end, path, coverage in [
        ("2025-09-01", "2026-09-01", "artifacts/research/annual-momentum/random10.parquet", recent),
        (
            "2022-09-01",
            "2025-09-01",
            "artifacts/research/annual-momentum/random10-temporal.parquet",
            temporal,
        ),
    ]:
        f = pd.read_parquet(path)
        if start == "2022-09-01":
            prior = sorted(f.loc[f.day < start, "day"].unique())[-273:]
            f = f[(f.day >= prior[0]) & (f.day < end)]
        syms, prepared = prepare(f, coverage)
        for i, perm in enumerate(itertools.permutations(SYMBOLS)):
            mapping = mapping_for(syms, prepared, perm)
            for mult in (1, 2):
                costs = dict(cfg["costs"])
                for k in (
                    "spread_bps",
                    "slippage_bps",
                    "commission_per_share",
                    "minimum_commission",
                    "sell_fee_bps",
                ):
                    costs[k] *= mult
                config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": 20})
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    r = simulate_positions(f, config, start, end, daily_bars=True)
                row = dict(
                    start=start,
                    end=end,
                    permutation=dict(zip(SYMBOLS, perm, strict=True)),
                    identity=list(perm) == SYMBOLS,
                    cost_multiplier=mult,
                    metrics=r["metrics"],
                )
                rows.append(row)
                full.append(dict(**row, result=r))
            dest.write_text(json.dumps(dict(status="running", results=rows), indent=2))
            print(start, i + 1, "/24", round(rows[-2]["metrics"]["return_pct"], 4), flush=True)
    archive = dest.with_suffix(".full.json.gz")
    archive.write_bytes(gzip.compress(json.dumps(full, separators=(",", ":")).encode(), mtime=0))
    summary = []
    for start in ["2025-09-01", "2022-09-01"]:
        for mult in (1, 2):
            rs = [r for r in rows if r["start"] == start and r["cost_multiplier"] == mult]
            actual = next(r for r in rs if r["identity"])["metrics"]["return_pct"]
            values = [r["metrics"]["return_pct"] for r in rs]
            summary.append(
                dict(
                    start=start,
                    cost_multiplier=mult,
                    identity_return_pct=actual,
                    strictly_higher=sum(v > actual + 1e-9 for v in values),
                    min_return_pct=min(values),
                    median_return_pct=float(np.median(values)),
                    max_return_pct=max(values),
                )
            )
    dest.write_text(
        json.dumps(
            dict(
                status="completed",
                validated=False,
                summary=summary,
                results=rows,
                full_archive=archive.name,
            ),
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
