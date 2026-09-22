"""Frozen course-inspired macro overlay experiment.

The overlay only scales the existing fixed ensemble by a causal pool trend and
breadth state.  Pools, dates, costs and execution settings are frozen from the
existing fixed-ensemble controls.
"""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path("docs/research-results")
OUT = ROOT / "2026-09-22-course-macro-overlay.json"


def main():
    controls = json.loads(
        __import__("gzip").decompress(
            (ROOT / "2026-09-22-trend-pullback.full.json.gz").read_bytes()
        )
    )["results"]
    manifest = json.loads((ROOT / "2026-09-21-annual-momentum-data.json").read_text())
    paths = {name: value["path"] for name, value in manifest.items()}
    paths.update(
        random10_temporal="artifacts/research/annual-momentum/random10-temporal.parquet",
        transfer12_temporal="artifacts/research/transfer12-temporal-2026-09-21/combined.parquet",
        new12_temporal="artifacts/research/liability-transfer-temporal/combined.parquet",
    )
    refs = {
        (r["pool"], r["cost_multiplier"]): r
        for r in controls
        if r["method"] == "fixed_ensemble" and r["policy"] == "legacy"
    }
    rows, sources = [], {}
    for (pool, multiplier), ref in sorted(refs.items()):
        path = Path(paths[pool])
        sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        frame = pd.read_parquet(path)
        start, end = ref["start"], ref["end_exclusive"]
        prior = sorted(frame.loc[frame.day < start, "day"].unique())[-273:]
        frame = frame[(frame.day >= prior[0]) & (frame.day < end)]
        macro_cfg = PositionConfig(**{**ref["config"], "model": "macro_overlay"})
        macro_map = rule_forecasts(frame, macro_cfg)
        for policy in ("legacy", "banded"):
            cfg = PositionConfig(**{**ref["config"], "model": "macro_overlay", "portfolio_policy": policy})
            with patch("quant_workbench.position.daily_forecasts", return_value=macro_map):
                result = simulate_positions(frame, cfg, start, end, daily_bars=True)
            for point in result["curve"]:
                assert point["cash"] >= -1e-6
                assert abs(point["equity"] - point["cash"] - sum(a["market_value"] for a in point["assets"].values())) < 1e-6
                assert abs(point["equity"] - 100000 - point["realized_pnl"] - point["unrealized_pnl"]) < 1e-6
            assert abs(sum(x["net_profit"] for x in result["contributions"]) - result["metrics"]["final_equity"] + 100000) < 1e-6
            rows.append(dict(pool=pool, start=start, end_exclusive=end, method="macro_overlay", policy=policy,
                             cost_multiplier=multiplier, checks=dict(conservation=True),
                             config=result["config"], metrics=result["metrics"],
                             contributions=result["contributions"], curve=result["curve"]))
            save_results(OUT, rows)
            m = result["metrics"]
            print(pool, multiplier, policy, f"return={m['return_pct']:.4f}", f"dd={m['max_drawdown_pct']:.4f}", flush=True)
    assert len(rows) == 24
    save_results(OUT, rows, completed=True)
    for source in [Path(__file__), Path("backend/src/quant_workbench/daily_strategies.py"), Path("backend/src/quant_workbench/position.py")]:
        sources[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    OUT.with_name(OUT.stem + "-sources.json").write_text(json.dumps(sources, indent=2) + "\n")


if __name__ == "__main__":
    main()
