"""Evaluate frozen generated policy; never train or tune on real evaluation data."""

import argparse
import json
from pathlib import Path

from principled_daily_study import run
from quant_workbench.position import PositionConfig
from quant_workbench.repository import Repository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="bfbd52245d674bd487bdd558295ad222")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-09-01")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/research-results/2026-09-18-generated-policy.json"),
    )
    args = parser.parse_args()
    ds = Repository().get("datasets", args.dataset)
    rows = []
    for policy in ("legacy", "cost_aware"):
        for multiplier in (1, 2):
            cfg = PositionConfig(
                model="generated_policy",
                portfolio_policy=policy,
                tranche_weight=0.1,
                entry_band=0.005,
            ).model_dump()
            for k in (
                "spread_bps",
                "slippage_bps",
                "commission_per_share",
                "minimum_commission",
                "sell_fee_bps",
            ):
                cfg["costs"][k] *= multiplier
            row = run(
                dict(
                    dataset=ds["id"],
                    method="generated_policy",
                    cost_multiplier=multiplier,
                    start=args.start,
                    end=args.end,
                    config=cfg,
                )
            )
            rows.append(row)
            print(
                policy,
                multiplier,
                row["metrics"]["return_pct"],
                row["metrics"]["max_drawdown_pct"],
                flush=True,
            )
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    training = json.loads(Path("artifacts/models/generated-policy-v1/training.json").read_text())
    output.write_text(
        json.dumps(dict(dataset=ds, training=training, results=rows), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
