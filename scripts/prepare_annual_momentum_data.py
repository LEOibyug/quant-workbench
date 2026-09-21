"""Extend fixed pools with raw pre-evaluation prices; never publish web datasets."""

import hashlib
import json
from pathlib import Path

import evaluate_alternate_universe as downloader
import pandas as pd
from quant_workbench.repository import Repository


def main():
    root = Path("artifacts/research/annual-momentum")
    root.mkdir(parents=True, exist_ok=True)
    meta = json.loads(Path("docs/research-results/2026-09-18-pattern-policy-v2.json").read_text())
    pools = {
        "original20": Repository().load_dataset(meta["combined_dataset"]["id"]),
        "alternate20": pd.read_parquet("artifacts/research/alternate-universe-2025/daily.parquet"),
        "random10": pd.read_parquet("artifacts/research/random-universe-2026-09-21/daily.parquet"),
    }
    report = {}
    for name, frame in pools.items():
        if name == "random10":
            prior = pd.read_parquet("artifacts/research/multiscale-temporal-random10/daily.parquet")
            prior = prior[prior.day >= "2024-08-01"]
        else:
            downloader.SYMBOLS = sorted(frame.symbol.unique())
            downloader.ROOT = root / name / "history"
            prior = downloader.download("2024-08-01", str(frame.day.min()))
        prior = prior[prior.day < str(frame.day.min())]
        combined = pd.concat([prior, frame], ignore_index=True).sort_values(["day", "symbol"])
        assert not combined.duplicated(["day", "symbol"]).any()
        # Source joins cannot silently introduce a split/scale discontinuity.
        for symbol, g in combined.groupby("symbol"):
            ratio = g.open.to_numpy()[1:] / g.close.to_numpy()[:-1]
            if ((ratio < 0.65) | (ratio > 1.5)).any():
                raise ValueError(f"{name}/{symbol}: unverified price discontinuity")
        path = root / f"{name}.parquet"
        combined.to_parquet(path, index=False)
        report[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": len(combined),
            "start": str(combined.day.min()),
            "end": str(combined.day.max()),
            "symbols": sorted(combined.symbol.unique()),
        }
        print(name, len(combined), flush=True)
    Path("docs/research-results/2026-09-21-annual-momentum-data.json").write_text(
        json.dumps(report, indent=2)
    )


if __name__ == "__main__":
    main()
