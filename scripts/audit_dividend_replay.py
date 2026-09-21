"""Fixed archived holdings, provisional ordinary USD-rate scenario; never a new strategy run."""

import gzip
import hashlib
import json
from bisect import bisect_left
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path("docs/research-results")
SOURCES = ["2026-09-21-transfer12", "2026-09-21-transfer12-temporal", "2026-09-21-tsmom"]


def replay(curve, initial_cash, events):
    days = [p["date"] for p in curve]
    assert days == sorted(set(days))
    symbols = set(curve[0]["positions"])
    assert all(n == 0 for n in curve[0]["positions"].values())
    assert curve[0]["cash"] == initial_cash
    for point in curve:
        assert set(point["positions"]) == symbols
        assert all(
            isinstance(n, int) and not isinstance(n, bool) and n >= 0
            for n in point["positions"].values()
        )
    counts = Counter((e["symbol"], e.get("ex_date")) for e in events)
    included, excluded = [], []
    recognition, settlements = {}, {}
    for e in events:
        if e["symbol"] not in symbols or not (days[0] <= e.get("ex_date", "") <= days[-1]):
            continue
        reasons = []
        if counts[e["symbol"], e["ex_date"]] != 1:
            reasons.append("ambiguous_same_day_identity")
        if e.get("foreign"):
            reasons.append("foreign")
        if e.get("special"):
            reasons.append("special")
        if any(e.get(k) for k in ["sub_type", "due_bill_on_date", "due_bill_off_date"]):
            reasons.append("special_terms")
        if e.get("currency") not in [None, "USD"]:
            reasons.append("non_usd")
        if e.get("rate", 0) <= 0:
            reasons.append("nonpositive_rate")
        if not e.get("payable_date") or e["payable_date"] < e["ex_date"]:
            reasons.append("invalid_payment_date")
        i = bisect_left(days, e["ex_date"])
        if i == len(days) or days[i] != e["ex_date"]:
            reasons.append("ex_date_not_in_sessions")
        if reasons:
            excluded.append(
                dict(id=e["id"], symbol=e["symbol"], ex_date=e["ex_date"], reasons=reasons)
            )
            continue
        shares = curve[i - 1]["positions"][e["symbol"]] if i else 0
        amount = Decimal(str(e["rate"])) * shares
        payment_index = bisect_left(days, e["payable_date"])
        payment_day = days[payment_index] if payment_index < len(days) else None
        included.append(
            dict(
                id=e["id"],
                symbol=e["symbol"],
                ex_date=e["ex_date"],
                preceding_shares=shares,
                source_rate=e["rate"],
                assumed_usd_amount=str(amount),
                source_payable_date=e["payable_date"],
                scenario_payment_day=payment_day,
                verified=False,
            )
        )
        recognition[e["ex_date"]] = recognition.get(e["ex_date"], Decimal(0)) + amount
        if payment_day:
            settlements[payment_day] = settlements.get(payment_day, Decimal(0)) + amount
    earned, paid = Decimal(0), Decimal(0)
    scenario = []
    for p in curve:
        earned += recognition.get(p["date"], Decimal(0))
        paid += settlements.get(p["date"], Decimal(0))
        receivable = earned - paid
        assert receivable >= 0
        scenario.append(
            dict(
                day=p["date"],
                original_equity=p["equity"],
                provisional_equity=p["equity"] + float(earned),
                additional_cash=str(paid),
                receivable=str(receivable),
            )
        )
    initial = Decimal(str(initial_cash))
    return dict(
        assumed_income=str(earned),
        assumed_paid=str(paid),
        assumed_receivable=str(earned - paid),
        addition_percentage_points=float(100 * earned / initial),
        events=included,
        excluded=excluded,
        provisional_curve=scenario,
    )


def main():
    event_path = ROOT / "2026-09-22-dividend-audit.json"
    events = json.loads(event_path.read_text())["events"]
    results = []
    hashes = {str(event_path): hashlib.sha256(event_path.read_bytes()).hexdigest()}
    for name in SOURCES:
        path = ROOT / (name + ".full.json.gz")
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        archive = json.loads(gzip.decompress(path.read_bytes()))
        assert archive["status"] == "completed"
        for row in archive["results"]:
            r = replay(row["curve"], row["config"]["costs"]["initial_cash"], events)
            results.append(
                dict(
                    source=name,
                    pool=(
                        "transfer12_temporal"
                        if name == "2026-09-21-transfer12-temporal"
                        else row["pool"]
                    ),
                    method=row["method"],
                    start=row["start"],
                    end_exclusive=row["end_exclusive"],
                    cost_multiplier=row["cost_multiplier"],
                    original_return_pct=row["metrics"]["return_pct"],
                    provisional_end_return_pct=row["metrics"]["return_pct"]
                    + r["addition_percentage_points"],
                    **r,
                )
            )
        print(name, len(results), "accounts", flush=True)
    assert len(results) == 82
    out = dict(
        status="completed",
        scope=(
            "Unverified source-rate sensitivity with frozen trades; "
            "no reinvestment or risk feedback"
        ),
        source_hashes=hashes,
        results=results,
    )
    (ROOT / "2026-09-22-dividend-replay.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    )


if __name__ == "__main__":
    main()
