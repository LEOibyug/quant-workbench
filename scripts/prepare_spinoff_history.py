"""Full child-asset marks for the frozen alternate-pool historical research period."""

import hashlib
import json
from pathlib import Path

import evaluate_alternate_universe as downloader


def main():
    results = []
    destination = Path("docs/research-results/2026-09-21-spinoff-history.json")
    for child, start in [("GEHC", "2023-01-04"), ("GEV", "2024-04-02"), ("KD", "2021-11-04")]:
        downloader.SYMBOLS = [child]
        downloader.ROOT = Path(f"artifacts/research/spinoff-history/{child}")
        frame = downloader.download(start, "2025-09-01")
        path = downloader.ROOT / "daily.parquet"
        results.append(
            dict(
                symbol=child,
                start=start,
                end_exclusive="2025-09-01",
                sessions=len(frame),
                path=str(path),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                guard="expected exchange sessions, unique rows, overnight ratio within [0.65,1.5]",
                full_corporate_action_audit=False,
            )
        )
        destination.write_text(json.dumps(dict(status="running", results=results), indent=2))
    destination.write_text(json.dumps(dict(status="completed", results=results), indent=2))


if __name__ == "__main__":
    main()
