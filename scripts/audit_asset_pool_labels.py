"""Compare pool-dependent labels at identical dates and unchanged asset growth."""

import json
from pathlib import Path

ROOT = Path("docs/research-results")


def label(decision, symbol):
    if symbol in decision["selected"]["low_growth"]:
        return "low"
    if symbol in decision["selected"]["high_growth"]:
        return "high"
    return "middle" if symbol in decision["eligible"] else "missing"


def main():
    old = json.loads((ROOT / "2026-09-22-asset-growth-coverage.json").read_text())
    new = json.loads((ROOT / "2026-09-22-asset-pool-coverage.json").read_text())
    comparisons = []
    for case in new:
        latest = case["pool"] == "merged62"
        pools = (
            ["original20", "alternate20", "random10", "transfer12"]
            if latest
            else ["random10_temporal", "transfer12_temporal"]
        )
        parts = [
            c
            for c in old
            if c["pool"] in pools and c["start"] == case["start"] and c["end"] == case["end"]
        ]
        assert len(parts) == len(pools)
        by_day = {d["day"]: d for d in case["coverage"]}
        rows = []
        for p in parts:
            assert {d["day"] for d in p["coverage"]} == set(by_day)
            for d in p["coverage"]:
                combined = by_day[d["day"]]
                for symbol, j in d["judgments"].items():
                    assert j == combined["judgments"][symbol]
                    if not j["computable"]:
                        continue
                    a, b = label(d, symbol), label(combined, symbol)
                    rows.append(
                        dict(
                            day=d["day"],
                            symbol=symbol,
                            original_pool=p["pool"],
                            growth=j["growth"],
                            original_label=a,
                            merged_label=b,
                            changed=a != b,
                        )
                    )
        comparisons.append(
            dict(
                pool=case["pool"],
                start=case["start"],
                end=case["end"],
                observations=len(rows),
                changed=sum(r["changed"] for r in rows),
                unchanged_financial_judgments=True,
                rows=rows,
            )
        )
    (ROOT / "2026-09-22-asset-pool-labels.json").write_text(
        json.dumps(dict(status="completed", comparisons=comparisons), indent=2) + "\n"
    )
    for c in comparisons:
        print(c["pool"], c["start"], c["end"], c["changed"], "/", c["observations"])


if __name__ == "__main__":
    main()
