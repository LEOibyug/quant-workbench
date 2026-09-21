"""Twenty predeclared account starts, same end and strategy, all results retained."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from asset_growth_forecasts import forecasts
from prepare_transfer12_fundamentals import EXCLUDED
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")


def main():
    data = Path("artifacts/research/asset-pool/merged22.parquet")
    frame = pd.read_parquet(data)
    end = "2025-09-01"
    starts = sorted(frame.loc[frame.day >= "2022-09-01", "day"].unique())[:20]
    assert len(starts) == 20 and starts[0] == "2022-09-01"
    identities = json.loads((ROOT / "2026-09-21-sec-50-issuers.json").read_text())
    info = json.loads((ROOT / "2026-09-21-transfer12-fundamentals.json").read_text())
    identities.update(
        {
            s: dict(identity_verified=r["current_identity_matched"])
            for s, r in info["issuers"].items()
        }
    )
    old = json.loads((ROOT / "2026-09-22-asset-pool.json").read_text())["results"]
    controls = {
        mult: next(
            r
            for r in old
            if r["pool"] == "merged22"
            and r["start"] == starts[0]
            and r["end_exclusive"] == end
            and r["method"] == "low_growth"
            and r["cost_multiplier"] == mult
        )
        for mult in [1, 2]
    }
    rows = []
    checks = []
    for start in starts:
        prior = sorted(frame.loc[frame.day < start, "day"].unique())[-273:]
        f = frame[(frame.day >= prior[0]) & (frame.day < end)]
        maps, coverage, _ = forecasts(
            f,
            start,
            end,
            facts_root=Path("artifacts/research/asset-pool/sec"),
            identities=identities,
            excluded=EXCLUDED,
        )
        expected = sorted(f.loc[f.day >= start, "day"].unique())[::20]
        assert [r["day"] for r in coverage] == expected
        for mult in [1, 2]:
            config = PositionConfig(**controls[mult]["config"])
            with patch("quant_workbench.position.daily_forecasts", return_value=maps["low_growth"]):
                r = simulate_positions(f, config, start, end, daily_bars=True)
            if start == starts[0]:
                assert r["metrics"] == controls[mult]["metrics"]
                assert r["contributions"] == controls[mult]["contributions"]
            halt = next((p["date"] for p in r["curve"] if p["halted"]), None)
            rows.append(
                dict(
                    pool="merged22",
                    start=start,
                    end_exclusive=end,
                    method="low_growth",
                    cost_multiplier=mult,
                    first_halt=halt,
                    config=r["config"],
                    metrics=r["metrics"],
                    contributions=r["contributions"],
                    curve=r["curve"],
                )
            )
            checks.append(
                dict(
                    start=start,
                    cost_multiplier=mult,
                    decision_calendar_checked=True,
                    control_exact=start == starts[0],
                )
            )
            print(
                start,
                mult,
                round(r["metrics"]["return_pct"], 4),
                round(r["metrics"]["max_drawdown_pct"], 4),
                halt,
                flush=True,
            )
    assert len(rows) == 40
    save_results(ROOT / "2026-09-22-start-sensitivity.json", rows, completed=True)
    (ROOT / "2026-09-22-start-sensitivity-checks.json").write_text(
        json.dumps(
            dict(
                starts=starts,
                end=end,
                checks=checks,
                data_sha256=hashlib.sha256(data.read_bytes()).hexdigest(),
                source_manifest="2026-09-22-asset-pool-data.json",
            ),
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
