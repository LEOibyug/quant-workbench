"""Unverified dividend-rate sensitivity with dynamic cash and risk feedback."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from cash_dividend_book import CashDividendBook
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def main():
    source = ROOT / "2026-09-22-dividend-audit.json"
    events = json.loads(source.read_text())["events"]
    counts = Counter((e["symbol"], e["ex_date"]) for e in events)
    archived = []
    hashes = {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}
    for name in ["2026-09-21-transfer12", "2026-09-21-transfer12-temporal"]:
        p = ROOT / (name + ".json")
        hashes[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        archived.extend(
            dict(r, source=name)
            for r in json.loads(p.read_text())["results"]
            if r["method"] == "fixed_ensemble"
        )
    static = json.loads((ROOT / "2026-09-22-dividend-replay.json").read_text())["results"]
    rows = []
    checks = []
    coverage = []
    for old in archived:
        start, end = old["start"], old["end_exclusive"]
        temporal = old["source"].endswith("temporal")
        path = Path(
            "artifacts/research/transfer12-temporal-2026-09-21/combined.parquet"
            if temporal
            else "artifacts/research/transfer12-2026-09-21/daily.parquet"
        )
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        f = pd.read_parquet(path)
        if temporal:
            prior = sorted(f.loc[f.day < start, "day"].unique())[-273:]
            f = f[(f.day >= prior[0]) & (f.day < end)]
        syms = set(f.symbol)
        selected = []
        excluded = []
        for e in events:
            if e["symbol"] not in syms or not start <= e["ex_date"] < end:
                continue
            special = any(
                e.get(k)
                for k in ["foreign", "special", "sub_type", "due_bill_on_date", "due_bill_off_date"]
            )
            invalid = (
                not e.get("payable_date")
                or e["payable_date"] < e["ex_date"]
                or e["rate"] <= 0
                or e.get("currency") not in (None, "USD")
            )
            if special or invalid or counts[e["symbol"], e["ex_date"]] != 1:
                excluded.append(e["id"])
                continue
            selected.append(
                dict(
                    e,
                    verified=False,
                    scenario_assumption="USD gross source rate",
                    kind="ordinary_cash",
                    amount_basis="gross",
                    evidence=[str(source)],
                )
            )
        cfg = PositionConfig(**old["config"])
        baseline = simulate_positions(f, cfg, start, end, daily_bars=True)
        assert (
            baseline["metrics"] == old["metrics"]
            and baseline["contributions"] == old["contributions"]
        )
        book = CashDividendBook(selected, source_rate_scenario=True)
        result = simulate_positions(f, cfg, start, end, daily_bars=True, research_dividends=book)
        assert all(e["verified"] is False for e in book.events)
        first = next(
            (e["day"] for e in book.audit if e["action"] == "recognize" and float(e["amount"]) > 0),
            None,
        )
        for a, b in zip(baseline["curve"], result["curve"], strict=True):
            d = b["dividends"]
            assert d["data_status"] == "unverified_source_rate_scenario"
            np.testing.assert_allclose(
                b["equity"],
                b["cash"] + sum(x["market_value"] for x in b["assets"].values()) + d["receivable"],
                rtol=0,
                atol=1e-7,
            )
            np.testing.assert_allclose(
                b["equity"] - cfg.costs.initial_cash,
                b["realized_pnl"] + b["unrealized_pnl"] + d["income"],
                rtol=0,
                atol=1e-7,
            )
            if first is None or b["date"] < first:
                assert all(a[k] == b[k] for k in ["equity", "cash", "positions", "halted"])
        np.testing.assert_allclose(
            sum(x["net_profit"] for x in result["contributions"]),
            result["metrics"]["final_equity"] - cfg.costs.initial_cash,
            rtol=0,
            atol=1e-7,
        )
        replay = next(
            r
            for r in static
            if r["source"] == old["source"]
            and r["method"] == "fixed_ensemble"
            and r["start"] == start
            and r["end_exclusive"] == end
            and r["cost_multiplier"] == old["cost_multiplier"]
        )
        for mode, r in [("baseline", baseline), ("source_rate_scenario", result)]:
            rows.append(
                dict(
                    pool="transfer12",
                    start=start,
                    end_exclusive=end,
                    method=mode,
                    cost_multiplier=old["cost_multiplier"],
                    config=r["config"],
                    metrics=r["metrics"],
                    curve=r["curve"],
                    contributions=r["contributions"],
                    dividend_audit=r.get("research_dividends"),
                    static_provisional_return_pct=replay["provisional_end_return_pct"],
                )
            )
        checks.append(
            dict(
                start=start,
                end=end,
                cost_multiplier=old["cost_multiplier"],
                baseline_exact=True,
                before_first_entitlement_exact=True,
                first_entitlement=first,
                conservation=True,
            )
        )
        coverage.append(
            dict(
                start=start,
                end=end,
                cost_multiplier=old["cost_multiplier"],
                selected=selected,
                excluded_ids=excluded,
            )
        )
        print(
            start,
            end,
            old["cost_multiplier"],
            baseline["metrics"]["return_pct"],
            result["metrics"]["return_pct"],
            result["metrics"]["halted"],
            flush=True,
        )
    assert len(rows) == 20
    save_results(ROOT / "2026-09-22-dividend-feedback.json", rows, completed=True)
    (ROOT / "2026-09-22-dividend-feedback-checks.json").write_text(
        json.dumps(dict(checks=checks, coverage=coverage, source_hashes=hashes), indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
