"""Planning estimates, not measurements of a vendor's files."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class StorageEstimate:
    rows: int
    compressed_bytes_low: int
    compressed_bytes_high: int
    working_bytes_high: int
    bytes_per_row_low: int = 24
    bytes_per_row_high: int = 64
    working_copies: int = 3
    basis: str = "OHLCV Parquet planning range; excludes features, models and tick data"


def estimate_storage(
    symbols: int = 7,
    years: float = 2,
    days_per_year: int = 252,
    minutes_per_day: int = 390,
    interval_seconds: int = 60,
) -> StorageEstimate:
    """Estimate regular-session bars with full-day budgeting, including half-day headroom."""
    for name, value in {
        "symbols": symbols,
        "days_per_year": days_per_year,
        "minutes_per_day": minutes_per_day,
        "interval_seconds": interval_seconds,
    }.items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if isinstance(years, bool) or not isinstance(years, int | float):
        raise ValueError("years must be a positive finite number")
    if not math.isfinite(years) or years <= 0:
        raise ValueError("years must be a positive finite number")
    if (minutes_per_day * 60) % interval_seconds:
        raise ValueError("interval_seconds must divide the regular session length")
    rows = math.ceil(symbols * years * days_per_year * minutes_per_day * 60 / interval_seconds)
    return StorageEstimate(rows, rows * 24, rows * 64, rows * 64 * 3)
