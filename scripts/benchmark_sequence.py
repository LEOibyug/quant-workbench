"""Synthetic end-to-end GRU latency benchmark; never reads or writes research data."""

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from quant_workbench.market_data import session_minutes
from quant_workbench.timeseries import TimeSeriesConfig, train_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--sessions", type=int, default=5, help="synthetic training sessions, 1–60")
    parser.add_argument("--online-bars", type=int, default=1950)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if not 1 <= args.sessions <= 60 or args.online_bars < 1:
        parser.error("sessions must be 1–60 and online-bars must be positive")
    rng = np.random.default_rng(21)
    timestamps = session_minutes("2024-01-02", "2024-04-01")[: args.sessions * 390]
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, len(timestamps))))
    opening = np.r_[close[0], close[:-1]]
    bars = pd.DataFrame(dict(
        timestamp=timestamps, symbol="NVDA", open=opening,
        high=np.maximum(opening, close) + 0.1, low=np.minimum(opening, close) - 0.1,
        close=close, volume=rng.integers(1000, 10000, len(timestamps)),
    ))
    config = TimeSeriesConfig(
        enabled=True, architecture="gru", k=30, horizon=5, max_iter=args.epochs,
        online_batch_size=16, replay_size=256,
    )
    records = bars.iloc[:args.online_bars].to_dict("records")
    # Exclude initial Python/CUDA library startup from repeated timings.
    warmup = train_model(bars.iloc[:390], config)
    device = warmup.estimator.device
    del warmup

    def synchronize():
        if device == "cuda":
            torch.cuda.synchronize()

    trials = []
    for _ in range(args.repeats):
        synchronize()
        start = time.perf_counter()
        model = train_model(bars, config)
        synchronize()
        training = time.perf_counter() - start
        start = time.perf_counter()
        for bar in records:
            model.predict(dict(
                symbol="NVDA", timestamp=bar["timestamp"], recent_bars=[bar],
                round_trip_cost_bps=8,
            ))
        synchronize()
        online = time.perf_counter() - start
        trials.append(dict(
            training_s=training, online_s=online,
            online_bars_per_s=len(records) / online,
            predictions=model.stats["predictions"], updates=model.stats["updates"],
        ))
        del model
    report = dict(
        synthetic=True, bars=len(bars), online_bars=len(records), symbols=1, device=device,
        gpu=torch.cuda.get_device_name() if device == "cuda" else None,
        torch=torch.__version__, config=config.model_dump(),
        cuda_graphs=os.environ.get("QUANT_CUDA_GRAPHS", "1"),
        train_cache_mib=os.environ.get("QUANT_TRAIN_CACHE_MIB", "256"),
        trials=trials,
        median_training_s=statistics.median(t["training_s"] for t in trials),
        median_online_s=statistics.median(t["online_s"] for t in trials),
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
