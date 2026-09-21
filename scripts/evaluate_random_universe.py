"""Draw once before download, then reuse the frozen untested-stock sample."""

import json
import random
import secrets
from datetime import UTC, datetime
from pathlib import Path

import evaluate_alternate_universe as evaluation

MANIFEST = Path("docs/research-results/2026-09-21-random-universe-protocol.json")
# A manually specified candidate pool; random within this pool, not all US equities.
POOL = sorted(
    "AMAT LRCX KLAC MU ADI SNPS CDNS NOW INTU ACN PANW CRWD FTNT DELL HPQ "
    "C WFC AXP BLK SCHW PGR CB MMC AON TMO ABT DHR AMGN GILD BMY MDT "
    "ISRG SBUX MCD NKE LOW TGT DIS CMCSA NFLX UPS UNP DE HON LMT RTX "
    "COP SLB EOG NEE DUK SO PLD AMT EQIX".split()
)


def main():
    original = json.loads(
        Path("docs/research-results/2026-09-18-pattern-policy-v2.json").read_text()
    )
    alternate = json.loads(
        Path("docs/research-results/2026-09-18-alternate-universe.json").read_text()
    )
    excluded = set(original["evaluation_dataset"]["symbols"]) | set(alternate["symbols"])
    assert not (set(POOL) & excluded)
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
    else:
        seed = secrets.randbits(64)
        selected = sorted(random.Random(seed).sample(POOL, 10))
        manifest = dict(
            created_at=datetime.now(UTC).isoformat(),
            seed=seed,
            sampling="Python random.Random(seed).sample(sorted pool, 10), without replacement",
            pool=POOL,
            symbols=selected,
            excluded=sorted(excluded),
            start="2025-09-01",
            end_exclusive="2026-09-01",
            warmup_start="2025-02-28",
            protocol="Freeze 10 symbols before downloading. No replacement based on results. "
            "Original fixed_ensemble effective configuration, shared cash 100000; "
            "normal/double cost and same-pool equal_weight controls. "
            "Stop and investigate incomplete data or price jumps; never silently drop a stock. "
            "No website registration. Candidate-pool selection is subjective; not a random "
            "sample of all listed US stocks, and time period previously studied.",
        )
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    assert manifest["symbols"] == sorted(
        random.Random(manifest["seed"]).sample(manifest["pool"], 10)
    )
    print("Frozen draw:", ", ".join(manifest["symbols"]), "seed:", manifest["seed"], flush=True)
    evaluation.SYMBOLS = manifest["symbols"]
    evaluation.ROOT = Path("artifacts/research/random-universe-2026-09-21")
    evaluation.REPORT = Path("docs/research-results/2026-09-21-random-universe.json")
    evaluation.main()
    report = json.loads(evaluation.REPORT.read_text())
    report["sampling_manifest"] = manifest
    evaluation.REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
