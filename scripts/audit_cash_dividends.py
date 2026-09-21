"""Read-only historical dividend source audit; no assertion of point-in-time completeness."""

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd
from quant_workbench.provider_windows import quarter_windows
from quant_workbench.providers import _get

ROOT = Path("docs/research-results")
CACHE = Path("artifacts/research/dividend-audit")


def main():
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    paths = [x["path"] for x in manifest.values()] + [
        "artifacts/research/transfer12-2026-09-21/daily.parquet"
    ]
    symbols = sorted(set().union(*(set(pd.read_parquet(p).symbol) for p in paths)))
    assert len(symbols) == 62
    CACHE.mkdir(parents=True, exist_ok=True)
    headers = {
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"],
    }
    events, sources = {}, []
    with httpx.Client(timeout=35) as client:
        for start, end in quarter_windows("2021-08-01", "2026-09-23"):
            # API end is inclusive; quarter_windows gives exclusive endpoints.
            stop = (date.fromisoformat(str(end)) - timedelta(days=1)).isoformat()
            params = dict(
                symbols=",".join(symbols),
                types="cash_dividend",
                start=str(start),
                end=stop,
                limit=1000,
            )
            seen = set()
            for page in range(100):
                path = CACHE / f"{start}-{stop}-{page}.json"
                if path.exists():
                    payload = json.loads(path.read_text())
                else:
                    response = _get(
                        client,
                        "https://data.alpaca.markets/v1/corporate-actions",
                        params=params,
                        headers=headers,
                    )
                    if response.status_code != 200:
                        raise ValueError(f"Dividend HTTP {response.status_code}")
                    payload = response.json()
                    path.write_text(json.dumps(payload, indent=2) + "\n")
                assert set(payload.get("corporate_actions", {})) <= {"cash_dividends"}
                for event in payload.get("corporate_actions", {}).get("cash_dividends", []):
                    assert event["symbol"] in symbols
                    assert str(start) <= event["process_date"] <= stop
                    if event["id"] in events and events[event["id"]] != event:
                        raise ValueError("Conflicting event ID")
                    events[event["id"]] = event
                sources.append(
                    dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                )
                token = payload.get("next_page_token")
                if not token:
                    break
                if token in seen:
                    raise ValueError("Repeated page token")
                seen.add(token)
                params["page_token"] = token
            else:
                raise ValueError("Pagination limit")
            print(start, stop, len(events), flush=True)
    rows = []
    for event in sorted(
        events.values(), key=lambda e: (e.get("ex_date", ""), e["symbol"], e["id"])
    ):
        issues = []
        if event.get("rate", 0) <= 0:
            issues.append("nonpositive_rate")
        if not event.get("currency"):
            issues.append("currency_unspecified")
        if not event.get("payable_date"):
            issues.append("missing_payment_date")
        if (
            event.get("special")
            or event.get("foreign")
            or event.get("sub_type")
            or event.get("due_bill_on_date")
            or event.get("due_bill_off_date")
        ):
            issues.append("requires_special_entitlement_review")
        ex = event.get("ex_date")
        delay = (
            (date.fromisoformat(event["process_date"]) - date.fromisoformat(ex)).days
            if ex
            else None
        )
        if not ex:
            issues.append("missing_ex_date")
        if ex and event.get("payable_date") and event["payable_date"] < ex:
            issues.append("payment_before_ex_date")
        rows.append(
            dict(**event, process_minus_ex_days=delay, issues=issues, point_in_time_verified=False)
        )
    keys = {}
    for r in rows:
        key = (r["symbol"], r.get("ex_date"), r.get("rate"), r.get("payable_date"))
        keys.setdefault(key, []).append(r["id"])
    duplicates = [dict(key=k, ids=v) for k, v in keys.items() if len(v) > 1]
    out = dict(
        status="completed",
        asof="2026-09-22",
        symbols=symbols,
        sources=sources,
        events=rows,
        potential_duplicate_economic_events=duplicates,
        point_in_time_complete=False,
        ex_date_coverage_complete=False,
        counts={s: sum(r["symbol"] == s for r in rows) for s in symbols},
    )
    (ROOT / "2026-09-22-dividend-audit.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    )
    print("completed", len(rows), "events", len(duplicates), "possible duplicates", flush=True)


if __name__ == "__main__":
    main()
