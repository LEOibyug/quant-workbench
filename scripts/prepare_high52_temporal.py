"""Extend the frozen random pool before its existing historical cache."""

from pathlib import Path

import evaluate_alternate_universe as downloader
import pandas as pd


def main():
    existing = pd.read_parquet("artifacts/research/multiscale-temporal-random10/daily.parquet")
    downloader.SYMBOLS = sorted(existing.symbol.unique())
    downloader.ROOT = Path("artifacts/research/annual-momentum/random10-earlier")
    earlier = downloader.download("2021-08-01", str(existing.day.min()))
    frame = pd.concat([earlier, existing], ignore_index=True).sort_values(["day", "symbol"])
    assert not frame.duplicated(["day", "symbol"]).any()
    frame.to_parquet("artifacts/research/annual-momentum/random10-temporal.parquet", index=False)


if __name__ == "__main__":
    main()
