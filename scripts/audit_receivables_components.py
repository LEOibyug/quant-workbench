"""Inspect all used new-issuer ratios and same-filing acquisition disclosures."""

import json
from pathlib import Path

ROOT = Path("docs/research-results")
TAGS = (
    "BusinessCombinationConsiderationTransferred1",
    "BusinessCombinationConsiderationTransferredEquityInterestsIssuedAndIssuable",
    "PaymentsToAcquireBusinessesNetOfCashAcquired",
)


def main():
    coverage = json.loads((ROOT / "2026-09-21-receivables-transfer12-coverage.json").read_text())
    seen = {}
    for window in coverage:
        for day in window["coverage"]:
            for symbol, j in day["judgments"].items():
                if j["computable"]:
                    seen[symbol, j["accession"]] = j
    output = []
    for j in seen.values():
        s = j["sources"]
        ar = s["receivables"]["val"]
        ar0 = s["prior_receivables"]["val"]
        rev = s["revenue"]["val"]
        rev0 = s["prior_revenue"]["val"]
        facts = json.loads(
            Path(f"artifacts/research/transfer12-sec/{j['symbol']}-facts.json").read_text()
        )["facts"]["us-gaap"]
        disclosures = []
        for tag in TAGS:
            for r in facts.get(tag, {}).get("units", {}).get("USD", []):
                if (
                    r.get("accn") == j["accession"]
                    and r.get("start") == s["revenue"]["start"]
                    and r.get("end") == j["fiscal_end"]
                ):
                    disclosures.append(dict(**r, tag=tag))
        ratio = (1 + (ar / ar0 - 1)) / (1 + (rev / rev0 - 1))
        assert abs(ratio - j["dsri"]) < 1e-12
        output.append(
            dict(
                symbol=j["symbol"],
                accession=j["accession"],
                fiscal_end=j["fiscal_end"],
                filed=s["revenue"]["filed"],
                dsri=j["dsri"],
                ar_growth_pct=100 * (ar / ar0 - 1),
                revenue_growth_pct=100 * (rev / rev0 - 1),
                receivables=ar,
                prior_receivables=ar0,
                revenue=rev,
                prior_revenue=rev0,
                acquisition_disclosures=disclosures,
                scope_comparability_verified=False,
            )
        )
    output.sort(key=lambda r: (r["symbol"], r["fiscal_end"]))
    (ROOT / "2026-09-21-receivables-components.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    print(len(output), "filing ratios reconstructed; scope remains unverified")


if __name__ == "__main__":
    main()
