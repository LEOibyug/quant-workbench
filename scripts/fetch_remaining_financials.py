"""Extend cached SEC issuer facts to all existing 50 stocks, preserving old audits."""

import json
import time
from pathlib import Path

import httpx
from build_quality_snapshots import CIKS, ROOT

EXTRA = {
    "AVGO": 1730168,
    "BRK.B": 1067983,
    "JPM": 19617,
    "LLY": 59478,
    "MA": 1141391,
    "ORCL": 1341439,
    "SOFI": 1818874,
    "V": 1403161,
    "WMT": 104169,
    "XOM": 34088,
    "BAC": 70858,
    "GS": 886982,
    "MS": 895421,
    "UNH": 731766,
    "ABBV": 1551152,
    "PEP": 77476,
    "HD": 354950,
    "GE": 40545,
    "CVX": 93410,
    "KO": 21344,
}


def main():
    index = {}
    ROOT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        timeout=40, headers={"User-Agent": "QuantWorkbench academic financial research client"}
    ) as client:
        for symbol, cik in {**CIKS, **EXTRA}.items():
            data = {}
            for kind, url in [
                ("facts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"),
                ("submission", f"https://data.sec.gov/submissions/CIK{cik:010d}.json"),
            ]:
                p = ROOT / f"{symbol}-{kind}.json"
                if not p.exists():
                    response = client.get(url)
                    if response.status_code != 200:
                        raise ValueError(f"{symbol} {kind}: HTTP {response.status_code}")
                    p.write_text(response.text)
                    time.sleep(0.25)
                data[kind] = json.loads(p.read_text())
            names = [s.replace("-", ".") for s in data["submission"]["tickers"]]
            index[symbol] = dict(
                cik=cik,
                entity=data["facts"]["entityName"],
                identity_verified=symbol in names,
                current_tickers=names,
            )
            print(
                symbol,
                "verified" if symbol in names else "identity requires historical review",
                flush=True,
            )
    Path("docs/research-results/2026-09-21-sec-50-issuers.json").write_text(
        json.dumps(index, indent=2)
    )


if __name__ == "__main__":
    main()
