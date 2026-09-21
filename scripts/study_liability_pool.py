"""Merged-universe asset growth diagnostic; frozen 30-account experiment."""

import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from verified_liability_features import judge
from asset_growth_forecasts import forecasts
from prepare_transfer12_fundamentals import CACHE, EXCLUDED
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def main():
    old = json.loads((ROOT / "2026-09-18-pattern-policy-v2.json").read_text())
    cfg = next(
        r["config"]
        for r in old["results"]
        if r["method"] == "fixed_ensemble" and r["cost_multiplier"] == 1
    )
    info = json.loads((ROOT / "2026-09-21-transfer12-fundamentals.json").read_text())
    identities = {
        s: {"identity_verified": r["current_identity_matched"]} for s, r in info["issuers"].items()
    }
    identities.update(json.loads((ROOT / "2026-09-21-sec-50-issuers.json").read_text()))
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    destination = Path("artifacts/research/asset-pool")
    facts = destination / "sec"
    source_hashes = {}
    for path in [destination / "merged62.parquet", destination / "merged22.parquet", *facts.glob("*-facts.json")]:
        source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    windows = [("merged62", destination / "merged62.parquet", "2025-09-01", "2026-09-01")]
    for start, end in [
        ("2022-09-01", "2023-09-01"),
        ("2023-09-01", "2024-09-01"),
        ("2024-09-01", "2025-09-01"),
        ("2022-09-01", "2025-09-01"),
    ]:
        windows.append(("merged22", destination / "merged22.parquet", start, end))
    (ROOT / "2026-09-22-liability-pool-data.json").write_text(
        json.dumps(source_hashes, indent=2) + "\n"
    )
    rows = []
    diagnostics = []
    dest = ROOT / "2026-09-22-liability-pool.json"
    for pool, path, start, end in windows:
        f = pd.read_parquet(path)
        prior = sorted(f.loc[f.day < start, "day"].unique())[-273:]
        frame = f if start == "2025-09-01" else f[(f.day >= prior[0]) & (f.day < end)]
        assert not frame.duplicated(["day", "symbol"]).any()
        pivot = frame.pivot(index="day", columns="symbol", values="close")
        assert pivot.notna().all().all() and (pivot > 0).all().all()
        kwargs = dict(facts_root=facts, identities=identities, excluded=EXCLUDED)
        maps, coverage, _ = forecasts(
            frame, start, end, judge_fn=judge, ratio_key="burden", **kwargs
        )
        middle = coverage[len(coverage)//2]['day']
        earlier, prior_coverage, _ = forecasts(frame[frame.day<=middle], start, end, judge_fn=judge, ratio_key='burden', **kwargs)
        assert prior_coverage == [d for d in coverage if d['day']<=middle]
        for mode in maps:
            assert earlier[mode] == {k:v for k,v in maps[mode].items() if k[0]<=middle}
        for decision in coverage:
            groups = decision["selected"]
            assert not set(groups["low_growth"]) & set(groups["high_growth"])
            for mapping in maps.values():
                weights = [
                    v["target_weight"] for (day, _), v in mapping.items() if day == decision["day"]
                ]
                assert all(0 <= w <= 0.2 + 1e-10 for w in weights)
                assert sum(weights) <= decision["budget"] + 1e-10
            for judgment in decision["judgments"].values():
                for source in judgment.get("sources", {}).values():
                    assert source["filed"] < decision["day"]
                    assert source["accn"] == judgment["accession"]
        diagnostics.append(dict(pool=pool, start=start, end=end, coverage=coverage))
        for mult in (1, 2):
            costs = dict(cfg["costs"])
            for key in (
                "spread_bps",
                "slippage_bps",
                "commission_per_share",
                "minimum_commission",
                "sell_fee_bps",
            ):
                costs[key] *= mult
            config = PositionConfig(**{**cfg, "costs": costs, "rebalance_days": 20})

            def record(method, r, pool=pool, start=start, end=end, mult=mult):
                rows.append(
                    dict(
                        pool=pool,
                        start=start,
                        end_exclusive=end,
                        method={"low_growth":"low_liability","high_growth":"high_liability","eligible":"eligible"}[method],
                        cost_multiplier=mult,
                        config=r["config"],
                        metrics=r["metrics"],
                        curve=r["curve"],
                        contributions=r["contributions"],
                    )
                )
                save_results(dest, rows, completed=False)
                print(
                    pool,
                    start,
                    method,
                    mult,
                    round(r["metrics"]["return_pct"], 4),
                    round(r["metrics"]["max_drawdown_pct"], 4),
                    flush=True,
                )

            for method, mapping in maps.items():
                with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
                    result = simulate_positions(frame, config, start, end, daily_bars=True)
                record(method, result)
    assert len(rows) == 30
    save_results(dest, rows, completed=True)
    (ROOT / "2026-09-22-liability-pool-coverage.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
