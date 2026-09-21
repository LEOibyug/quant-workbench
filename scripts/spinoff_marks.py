"""Exact-session side-asset valuation; never forward-fill missing child prices."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


class ChildMarks:
    def __init__(self, manifest):
        data = json.loads(Path(manifest).read_text())
        if data["status"] != "completed":
            raise ValueError("Incomplete child history manifest")
        self.frames = {}
        for item in data["results"]:
            path = Path(item["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Child data hash mismatch")
            f = pd.read_parquet(path)
            if f.day.duplicated().any() or set(f.symbol) != {item["symbol"]}:
                raise ValueError("Invalid child panel")
            prices = f[["open", "close"]].to_numpy()
            if not np.isfinite(prices).all() or (prices <= 0).any():
                raise ValueError("Invalid child prices")
            self.frames[item["symbol"]] = f.set_index("day")

    def at(self, day, symbols, field):
        if field not in ("open", "close"):
            raise ValueError("Only same-session open/close marks supported")
        result = {}
        for symbol in symbols:
            if symbol not in self.frames or day not in self.frames[symbol].index:
                raise ValueError(f"Missing exact-session child price: {symbol} {day}")
            result[symbol] = float(self.frames[symbol].loc[day, field])
        return result
