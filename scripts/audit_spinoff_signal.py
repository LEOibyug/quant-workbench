"""Measure known distribution corrections without claiming complete total returns."""

import hashlib
import json
from pathlib import Path

import pandas as pd
from spinoff_signal import forward_index


def main():
    source = Path("artifacts/research/alternate-history/daily.parquet")
    frame = pd.read_parquet(source)
    quotes = json.loads(Path("docs/research-results/2026-09-21-spinoff-quotes.json").read_text())
    gev = json.loads(
        Path("docs/research-results/2026-09-21-gev-verified-distribution.json").read_text()
    )
    confirmed = json.loads(
        Path("docs/research-results/2026-09-21-spinoff-reconciliation.json").read_text()
    )
    events = []
    for q in quotes:
        verified = (
            gev["ratio_verified"]
            if q["child"] == "GEV"
            else next(e["ratio_verified"] for e in confirmed if e["child"] == q["child"])
        )
        denominator = {"GEHC": 3, "GEV": 4, "KD": 5}[q["child"]]
        child = pd.read_parquet(q["path"])
        assert hashlib.sha256(Path(q["path"]).read_bytes()).hexdigest() == q["sha256"]
        price = child.loc[child.day == q["first_regular_session"], "close"].item()
        events.append(
            dict(
                id=q["child"],
                parent=q["parent"],
                day=q["first_regular_session"],
                numerator=1,
                denominator=denominator,
                child_close=price,
                child_price_day=q["first_regular_session"],
                verified=verified,
            )
        )
    rows = []
    for symbol in ["GE", "IBM"]:
        close = frame[frame.symbol == symbol].sort_values("day").set_index("day").close
        applicable = [e for e in events if e["parent"] == symbol]
        adjusted = forward_index(close, applicable)
        for e in applicable:
            day = e["day"]
            i = close.index.get_loc(day)
            prefix = forward_index(close.iloc[:i], applicable)
            assert prefix.equals(adjusted.iloc[:i])
            rows.append(
                dict(
                    **e,
                    parent_previous_close=float(close.iloc[i - 1]),
                    parent_close=float(close.iloc[i]),
                    raw_close_return_pct=float((close.iloc[i] / close.iloc[i - 1] - 1) * 100),
                    corrected_close_return_pct=float(
                        (adjusted.iloc[i] / adjusted.iloc[i - 1] - 1) * 100
                    ),
                )
            )
    report = dict(
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        events=rows,
        scope="Three known spinoffs; theoretical close reinvestment index, not account PnL",
    )
    Path("docs/research-results/2026-09-21-spinoff-signal.json").write_text(
        json.dumps(report, indent=2)
    )
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
