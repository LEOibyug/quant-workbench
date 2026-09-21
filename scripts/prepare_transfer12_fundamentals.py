"""Fetch and audit additional issuers; ticker/CIK matching is not historical identity proof."""

import hashlib
import json
import time
from pathlib import Path

import httpx
from audit_receivables_quality import judge

ROOT = Path("docs/research-results")
CACHE = Path("artifacts/research/transfer12-sec")
# Lookup candidates, accepted only after the SEC submission itself matches.
CIKS = dict(
    ABT=1800,
    ADP=8670,
    AMT=1053507,
    BLK=2012383,
    CME=1156375,
    DUK=1326160,
    LIN=1707925,
    MDT=1613103,
    SPGI=64040,
    UPS=1090727,
    USB=36104,
    VZ=732712,
)
EXCLUDED = dict(
    AMT="REIT", BLK="asset manager", CME="financial exchange", DUK="regulated utility", USB="bank"
)


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    issuers = {}
    results = []
    with httpx.Client(
        timeout=30, headers={"User-Agent": "QuantWorkbench financial research local client"}
    ) as client:
        for symbol, cik in CIKS.items():
            sources = {}
            payloads = {}
            errors = []
            for kind, url in [
                ("submission", f"https://data.sec.gov/submissions/CIK{cik:010d}.json"),
                ("facts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"),
            ]:
                path = CACHE / f"{symbol}-{kind}.json"
                if not path.exists():
                    try:
                        response = client.get(url)
                        if response.status_code != 200:
                            errors.append(dict(kind=kind, http_status=response.status_code))
                            continue
                        value = response.json()
                        path.write_text(json.dumps(value))
                    except (httpx.HTTPError, ValueError) as e:
                        errors.append(dict(kind=kind, error=type(e).__name__))
                        continue
                    time.sleep(0.2)
                payloads[kind] = json.loads(path.read_text())
                sources[kind] = dict(
                    url=url, path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()
                )
            sub = payloads.get("submission", {})
            facts = payloads.get("facts", {})
            verified = (
                str(sub.get("cik", "")).lstrip("0") == str(cik)
                and symbol in sub.get("tickers", [])
                and str(facts.get("cik", "")).lstrip("0") == str(cik)
            )
            issuers[symbol] = dict(
                cik=cik,
                current_identity_matched=verified,
                historical_identity_verified=False,
                name=sub.get("name"),
                facts_name=facts.get("entityName"),
                sic=sub.get("sic"),
                sic_description=sub.get("sicDescription"),
                excluded_reason=EXCLUDED.get(symbol),
                sources=sources,
                errors=errors,
            )
            for day in ["2022-09-01", "2023-09-01", "2024-09-01", "2025-09-01", "2026-09-01"]:
                r = judge(facts, symbol, day, verified and symbol not in EXCLUDED)
                r["identity_scope"] = "current ticker/CIK only; historical continuity not audited"
                if symbol in EXCLUDED:
                    r["reason"] = "预定不可比业务范围: " + EXCLUDED[symbol]
                results.append(r)
            print(
                symbol,
                "current match",
                verified,
                "computable",
                sum(r["computable"] for r in results if r["symbol"] == symbol),
                flush=True,
            )
            (ROOT / "2026-09-21-transfer12-fundamentals.json").write_text(
                json.dumps(
                    dict(status="running", issuers=issuers, results=results),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    (ROOT / "2026-09-21-transfer12-fundamentals.json").write_text(
        json.dumps(
            dict(status="completed", issuers=issuers, results=results), ensure_ascii=False, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
