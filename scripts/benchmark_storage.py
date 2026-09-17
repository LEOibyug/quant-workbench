"""Measure synthetic OHLCV Parquet footprint; never generates market evidence."""

import json
import tempfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

SYMBOLS = ["NVDA", "TSLA", "AAPL", "AMD", "SOFI", "SPY", "QQQ"]
MINUTES = 390
DAYS = 504


def main() -> None:
    rng = np.random.default_rng(20260917)
    timestamps = (
        np.datetime64("2024-01-01T14:30", "ns")
        + np.repeat(np.arange(DAYS), MINUTES) * np.timedelta64(1, "D")
        + np.tile(np.arange(MINUTES), DAYS) * np.timedelta64(1, "m")
    )
    total_rows = 0
    file_count = 0
    uncompressed_bytes = 0
    with tempfile.TemporaryDirectory(prefix="quant-storage-") as temporary:
        root = Path(temporary)
        for symbol in SYMBOLS:
            count = DAYS * MINUTES
            close = np.round(100 * np.exp(np.cumsum(rng.normal(0, 0.0008, count))), 2)
            opening = np.concatenate(([100.0], close[:-1]))
            spread = rng.uniform(0.01, 0.3, count)
            table = pa.table(
                {
                    "timestamp": pa.array(timestamps, type=pa.timestamp("ns", tz="UTC")),
                    "symbol": [symbol] * count,
                    "open": opening,
                    "high": np.round(np.maximum(opening, close) + spread, 2),
                    "low": np.round(np.minimum(opening, close) - spread, 2),
                    "close": close,
                    "volume": rng.integers(100, 100_000, count, dtype=np.int64),
                }
            )
            total_rows += count
            uncompressed_bytes += table.nbytes
            # Twenty synthetic days per file to approximate monthly partitions.
            for start in range(0, count, MINUTES * 20):
                pq.write_table(
                    table.slice(start, MINUTES * 20),
                    root / f"{symbol}-{start}.parquet",
                    compression="zstd",
                )
                file_count += 1
        compressed_bytes = sum(p.stat().st_size for p in root.glob("*.parquet"))
    print(
        json.dumps(
            {
                "synthetic": True,
                "calendar": "504 artificial sessions, not an exchange calendar",
                "rows": total_rows,
                "files": file_count,
                "arrow_bytes": uncompressed_bytes,
                "parquet_bytes": compressed_bytes,
                "compressed_bytes_per_row": round(compressed_bytes / total_rows, 2),
                "temporary_files_removed": True,
                "limitations": "No trades, quotes, features, corporate actions or vendor metadata",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
