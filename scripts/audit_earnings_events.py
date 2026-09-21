"""Map SEC Item 2.02 acceptance timestamps to fully observed market sessions."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
from quant_workbench.market_data import schedule


def events(submission, start, end):
    recent = submission.get("filings", {}).get("recent", {})
    cal = schedule(start, (pd.Timestamp(end) + pd.Timedelta(days=14)).strftime("%Y-%m-%d"))
    closes = pd.to_datetime(cal["close"], utc=True)
    output = []
    for i, form in enumerate(recent.get("form", [])):
        if form != "8-K" or "2.02" not in recent["items"][i].split(","):
            continue
        timestamp = recent.get("acceptanceDateTime", [])[i]
        accepted = pd.Timestamp(timestamp)
        if accepted.tzinfo is None:
            raise ValueError("Ambiguous SEC timestamp timezone")
        accepted = accepted.tz_convert("UTC")
        day = accepted.tz_convert("America/New_York").strftime("%Y-%m-%d")
        if not start <= day < end:
            continue
        k = int(closes.searchsorted(accepted, side="right"))
        if k >= len(cal):
            raise ValueError("Missing next market close")
        session = str(cal.index[k].date())
        opening = pd.Timestamp(cal.iloc[k]["open"]).tz_convert("UTC")
        output.append(
            dict(
                accession=recent["accessionNumber"][i],
                acceptance_utc=accepted.isoformat(),
                filing_date=recent["filingDate"][i],
                report_date=recent["reportDate"][i],
                observation_session=session,
                observation_close_utc=closes.iloc[k].isoformat(),
                before_observation_open=bool(accepted < opening),
                same_local_day=session == day,
                primary_document=recent["primaryDocument"][i],
            )
        )
    return sorted(output, key=lambda r: r["acceptance_utc"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", default="2022-09-01")
    p.add_argument("--end", default="2026-09-01")
    p.add_argument(
        "--output",
        type=Path,
        default=Path("docs/research-results/2026-09-21-earnings-event-audit.json"),
    )
    p.add_argument("--submissions", type=Path, default=Path("artifacts/research/sec-quality"))
    a = p.parse_args()
    out = {}
    identities = json.loads(
        Path("docs/research-results/2026-09-21-sec-50-issuers.json").read_text()
    )
    for path in sorted(a.submissions.glob("*-submission.json")):
        symbol = path.name.removesuffix("-submission.json")
        d = json.loads(path.read_text())
        recent = d["filings"]["recent"]
        dates = recent["filingDate"]
        out[symbol] = dict(
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            current_identity_verified=identities.get(symbol, {}).get("identity_verified", False),
            earliest_cached_filing=min(dates),
            latest_cached_filing=max(dates),
            cache_starts_before_window=min(dates) < a.start,
            events=events(d, a.start, a.end),
            older_submission_files=d["filings"].get("files", []),
        )
    a.output.write_text(json.dumps(dict(start=a.start, end_exclusive=a.end, issuers=out), indent=2))
    print(
        "issuers",
        len(out),
        "events",
        sum(len(v["events"]) for v in out.values()),
        "cache starts before window",
        sum(v["cache_starts_before_window"] for v in out.values()),
    )


if __name__ == "__main__":
    main()
