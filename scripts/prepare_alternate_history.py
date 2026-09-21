"""Download fixed alternate-pool history and preserve audit failures explicitly."""

import hashlib
import json
from pathlib import Path

import evaluate_alternate_universe as downloader
import pandas as pd
from quant_workbench.market_data import schedule


def main():
    root = Path("artifacts/research/alternate-history")
    downloader.ROOT = root
    start, end = "2021-08-01", "2025-09-01"
    failure = None
    try:
        downloader.download(start, end)
    except ValueError as error:
        failure = str(error)
    chunks = sorted(root.glob("*-raw.parquet"))
    if not chunks:
        raise ValueError("No cached chunks")
    frame = pd.concat([pd.read_parquet(p) for p in chunks], ignore_index=True).sort_values(
        ["symbol", "day"]
    )
    expected = set(schedule(start, end).index.strftime("%Y-%m-%d"))
    duplicates = int(frame.duplicated(["symbol", "day"]).sum())
    missing = {
        s: sorted(expected - set(frame.loc[frame.symbol == s, "day"])) for s in downloader.SYMBOLS
    }
    jumps = []
    for symbol, g in frame.groupby("symbol"):
        g = g.sort_values("day")
        ratio = g.open.to_numpy()[1:] / g.close.to_numpy()[:-1]
        for i, value in enumerate(ratio):
            if value < 0.65 or value > 1.5:
                jumps.append(
                    dict(
                        symbol=symbol,
                        day=g.day.iloc[i + 1],
                        previous_close=float(g.close.iloc[i]),
                        open=float(g.open.iloc[i + 1]),
                        ratio=float(value),
                    )
                )
    corporate_review = []
    # Explicit known event dates warrant review even below the coarse jump threshold.
    for symbol, day in [("GE", "2023-01-04"), ("GE", "2024-04-02"), ("IBM", "2021-11-04")]:
        g = frame[frame.symbol == symbol].sort_values("day").reset_index(drop=True)
        found = g.index[g.day == day].tolist()
        if found and found[0] > 0:
            i = found[0]
            corporate_review.append(
                dict(
                    symbol=symbol,
                    day=day,
                    previous_close=float(g.close.iloc[i - 1]),
                    open=float(g.open.iloc[i]),
                    ratio=float(g.open.iloc[i] / g.close.iloc[i - 1]),
                    status="公司分拆权益未核验和入账，不能直接raw回测",
                )
            )
    report = dict(
        start=start,
        end_exclusive=end,
        symbols=downloader.SYMBOLS,
        rows=len(frame),
        chunks={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in chunks},
        duplicates=duplicates,
        missing_sessions=missing,
        price_jumps=jumps,
        corporate_action_review=corporate_review,
        downloader_failure=failure,
        ready_for_evaluation=not corporate_review
        and not failure
        and not duplicates
        and not any(missing.values())
        and not jumps,
    )
    Path("docs/research-results/2026-09-21-alternate-history-audit.json").write_text(
        json.dumps(report, indent=2)
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("chunks", "missing_sessions")}, indent=2
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
