"""Causal OHLCV sequences shared by offline training and streaming inference."""

import math
from collections import deque

import numpy as np
import pandas as pd

LONG_STEPS = 78
TOKEN_NAMES = [
    "return_pct",
    "body_pct",
    "high_pct",
    "low_pct",
    "log_volume",
    "time_sin",
    "time_cos",
]


def contiguous(left, right, minutes=1):
    return (
        left is not None
        and right - left == pd.Timedelta(minutes=minutes)
        and left.tz_convert("America/New_York").date()
        == right.tz_convert("America/New_York").date()
    )


def token(bar, previous_close, timestamp):
    local = timestamp.tz_convert("America/New_York")
    angle = 2 * math.pi * (local.hour * 60 + local.minute - 570) / 390
    base = previous_close if previous_close is not None else bar["open"]
    return np.array(
        [
            100 * math.log(bar["close"] / base),
            100 * math.log(bar["close"] / bar["open"]),
            100 * math.log(bar["high"] / bar["open"]),
            100 * math.log(bar["low"] / bar["open"]),
            math.log1p(bar["volume"]),
            math.sin(angle),
            math.cos(angle),
        ],
        dtype=np.float32,
    )


class SequenceHistory:
    def __init__(self, k):
        self.short = deque(maxlen=k)
        self.long = deque(maxlen=LONG_STEPS)
        self.aggregate = []
        self.last_time = self.last_close = self.long_time = self.long_close = None

    def observe(self, bar, timestamp):
        ts = pd.Timestamp(timestamp)
        if self.last_time is not None and ts <= self.last_time:
            raise ValueError("sequence timestamps must increase")
        complete = contiguous(self.last_time, ts)
        if not complete:
            self.short.clear()
            self.aggregate.clear()
        self.short.append(token(bar, self.last_close if complete else None, ts))
        self.aggregate.append(bar)
        # Align to the exchange clock, never fabricate a 5-minute candle over a gap.
        local = ts.tz_convert("America/New_York")
        if (local.hour * 60 + local.minute - 570) % 5 == 0:
            if len(self.aggregate) == 5:
                group = self.aggregate
                combined = dict(
                    open=group[0]["open"],
                    close=bar["close"],
                    high=max(b["high"] for b in group),
                    low=min(b["low"] for b in group),
                    volume=sum(b["volume"] for b in group),
                )
                base = self.long_close if contiguous(self.long_time, ts, 5) else None
                self.long.append(token(combined, base, ts))
                self.long_time, self.long_close = ts, bar["close"]
            self.aggregate.clear()
        self.last_time, self.last_close = ts, bar["close"]

    def snapshot(self, background, feedback):
        long = np.zeros((LONG_STEPS, len(TOKEN_NAMES)), dtype=np.float32)
        size = len(self.long)
        if size:
            long[:size] = np.stack(self.long)
        return dict(
            short=np.stack(self.short).astype(np.float32),
            long=long,
            length=np.array(max(1, size), dtype=np.int64),
            context=np.concatenate([background.ravel(), feedback.ravel()]).astype(np.float32),
        )


def stack_samples(samples):
    return {key: np.stack([sample[key] for sample in samples]) for key in samples[0]}
