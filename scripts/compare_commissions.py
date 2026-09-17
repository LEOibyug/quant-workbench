"""Commission-only sensitivity on frozen validation forecasts, never the test set.

These are principal commission scenarios, not replicas of broker statements.
Exchange/clearing fees, share-based regulatory charges and per-order caps are
not represented by the engine's generic sell-fee approximation.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from compare_entry_fusion import ForecastReplay, summarize
from quant_workbench.engine import simulate
from quant_workbench.models import StrategyConfig
from quant_workbench.repository import Repository

PROFILES = {
    "conservative": {"commission_per_share": 0.005, "minimum_commission": 1.0},
    "alpaca_self_directed": {"commission_per_share": 0.0, "minimum_commission": 0.0},
    "ibkr_pro_tiered_base": {"commission_per_share": 0.0035, "minimum_commission": 0.35},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--original", required=True)
    args = parser.parse_args()
    out = args.directory
    repo = Repository()
    old = repo.get("experiments", args.original)
    new = json.loads((out / "improved-experiment.json").read_text())
    for key in ("dataset_id", "train_end", "validation_end", "symbols"):
        if old[key] != new[key]:
            raise ValueError(f"mismatched comparison: {key}")
    frame = repo.load_dataset(old["dataset_id"])
    frame = frame[frame.symbol.isin(old["symbols"])]
    report = {
        "scope": "commission_only_sensitivity",
        "start": old["train_end"],
        "end_exclusive": old["validation_end"],
        "dataset_sha256": old["dataset_sha256"],
        "assumptions": [
            "Only principal commission changes; same frozen causal forecasts and validation bars.",
            "Orders, quantities, rule gates and portfolio paths are simulated again.",
            "Spread 2 bps full width, slippage 2 bps/side, generic sell fee 0.3 bps.",
            "Minimum applies per fill in this engine; actual broker minimum is per order.",
            "IBKR first volume tier base only; exchange/clearing/pass-through fees omitted.",
            "Broker fee caps and dated per-share regulatory fees are not modeled.",
            "Current published commissions are scenarios, not reconstructed 2025 invoices.",
            "Alpaca zero commission assumes a qualifying self-directed retail account.",
        ],
        "results": {},
    }
    for variant, source, trace_name, mode in [
        ("legacy_strict", old, "legacy-validation-trace.json", "strict"),
        ("normalized_overlay", new, "improved-validation-trace.json", "risk_scaled"),
    ]:
        trace = json.loads((out / trace_name).read_text())
        report["results"][variant] = {}
        for profile, fees in PROFILES.items():
            cfg = StrategyConfig(**(source["config"] | fees))
            if (cfg.spread_bps, cfg.slippage_bps, cfg.sell_fee_bps) != (2, 2, 0.3):
                raise ValueError("Update documented execution assumptions before comparing")
            result = simulate(
                frame,
                cfg,
                old["train_end"],
                old["validation_end"],
                source["strategies"],
                ForecastReplay(trace, mode, source["model"]),
            )
            if profile == "conservative" and not np.isclose(
                result["metrics"]["final_equity"],
                trace["metrics"]["final_equity"],
                rtol=0,
                atol=1e-6,
            ):
                raise ValueError("Replay failed to reproduce frozen validation equity")
            report["results"][variant][profile] = {"commission": fees, **summarize(result)}
            (out / f"fees-{variant}-{profile}.json").write_text(
                json.dumps(result, ensure_ascii=False, allow_nan=False)
            )
            print(variant, profile, json.dumps(result["metrics"]), flush=True)
    (out / "commission-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    )


if __name__ == "__main__":
    main()
