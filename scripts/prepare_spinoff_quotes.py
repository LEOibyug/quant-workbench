"""Fetch first regular-session child quotes for unresolved historical distributions."""

import hashlib
import json
from pathlib import Path

import evaluate_alternate_universe as downloader


def main():
    events = [
        ("GE", "GEHC", "2023-01-04", "2023-01-11", 1 / 3),
        ("GE", "GEV", "2024-04-02", "2024-04-09", 1 / 4),
        ("IBM", "KD", "2021-11-04", "2021-11-11", 1 / 5),
    ]
    results = []
    for parent, child, start, end, ratio in events:
        downloader.SYMBOLS = [child]
        downloader.ROOT = Path(f"artifacts/research/spinoff-quotes/{child}")
        frame = downloader.download(start, end)
        first = frame[frame.day == start].iloc[0]
        path = downloader.ROOT / "daily.parquet"
        results.append(
            dict(
                parent=parent,
                child=child,
                first_regular_session=start,
                candidate_ratio=ratio,
                ratio_requires_source_verification=True,
                first_open=float(first.open),
                first_close=float(first.close),
                path=str(path),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    Path("docs/research-results/2026-09-21-spinoff-quotes.json").write_text(
        json.dumps(results, indent=2)
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
