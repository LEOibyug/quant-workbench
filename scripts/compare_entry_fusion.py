"""Replay causal model forecasts across frozen rule/fusion ablations (validation only).

Forecasts are independent of executions: features use bars and matured price labels,
not cash/positions. Recompute cost gates at each counterfactual portfolio state.
No new network fitting or future prediction lookup happens during a replay.
"""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from quant_workbench.engine import simulate
from quant_workbench.fusion import risk_overlay
from quant_workbench.models import StrategyConfig
from quant_workbench.repository import Repository


class ForecastReplay:
    def __init__(self, result, mode, model_config):
        self.lookup = {(p["symbol"], p["timestamp"]): p for p in result["market_curve"]}
        self.config = SimpleNamespace(decision_mode=mode)
        self.model_config = model_config
        self.audit = []
        self.stats = result.get("model_statistics", {})

    def predict(self, context):
        point = self.lookup[(context["symbol"], context["timestamp"])]
        p, expected = point["probability"], point["expected_return_bps"]
        cost = context["round_trip_cost_bps"]
        fraction, edge = 1.0, None
        if p is None:
            allow, fraction = False, 0.0
        elif self.config.decision_mode == "risk_scaled":
            allow, fraction = risk_overlay(p, expected, cost)
        else:
            allow = p >= self.model_config["probability_threshold"]
            if self.model_config["cost_aware"]:
                edge = (
                    None
                    if cost is None
                    else cost * self.model_config["cost_multiplier"]
                    + self.model_config["min_edge_bps"]
                )
                allow = allow and edge is not None and expected is not None and expected > edge
        return dict(
            allow_entry=bool(allow),
            probability=p,
            expected_return_bps=expected,
            required_edge_bps=edge,
            risk_fraction=fraction,
        )


def summarize(result):
    trades = result["trades"]
    sessions = len(result["daily_returns"])
    half = sessions // 2
    returns = np.array([r["return_pct"] for r in result["daily_returns"]]) / 100
    return dict(
        metrics=result["metrics"],
        contributions=result["contributions"],
        first_half_return_pct=float((np.prod(1 + returns[:half]) - 1) * 100),
        second_half_return_pct=float((np.prod(1 + returns[half:]) - 1) * 100),
        traded_sessions=len({t["timestamp"][:10] for t in trades}),
        per_symbol={
            c["symbol"]: dict(
                net_profit=c["net_profit"],
                entries=sum(t["symbol"] == c["symbol"] and t["side"] == "buy" for t in trades),
                traded_sessions=len(
                    {t["timestamp"][:10] for t in trades if t["symbol"] == c["symbol"]}
                ),
            )
            for c in result["contributions"]
        },
        decision_funnel=result.get("decision_funnel"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--original", required=True)
    args = parser.parse_args()
    out = args.directory
    repo = Repository()
    old = repo.get("experiments", args.original)
    new = json.loads((out / "improved-experiment.json").read_text())
    if (old["train_end"], old["validation_end"], old["dataset_id"]) != (
        new["train_end"],
        new["validation_end"],
        new["dataset_id"],
    ):
        raise ValueError("comparison requires the same validation dataset and dates")
    frame = repo.load_dataset(old["dataset_id"])
    old_trace = json.loads((out / "legacy-validation-trace.json").read_text())
    new_trace = json.loads((out / "improved-validation-trace.json").read_text())
    variants = [
        ("legacy-strict", old, old_trace, "strict"),
        ("legacy-overlay", old, old_trace, "risk_scaled"),
        ("new-rule-old-model", new, old_trace, "risk_scaled"),
        ("normalized-strict", new, new_trace, "strict"),
        ("normalized-overlay", new, new_trace, "risk_scaled"),
    ]
    selected_path = out / "development-rule-selection.json"
    if selected_path.exists():
        selection = json.loads(selected_path.read_text())
        chosen = {**new, "config": old["config"], "strategies": selection["selection"]}
        variants.append(("development-selected-normalized", chosen, new_trace, "risk_scaled"))
    report = {}
    for name, source, trace, mode in variants:
        model_config = (old if trace is old_trace else new)["model"]
        filt = ForecastReplay(trace, mode, model_config)
        result = simulate(
            frame,
            StrategyConfig(**source["config"]),
            old["train_end"],
            old["validation_end"],
            source["strategies"],
            filt,
            record_market=True,
        )
        if name == "legacy-strict":
            if not np.isclose(
                result["metrics"]["final_equity"], old_trace["metrics"]["final_equity"]
            ):
                raise ValueError("cached forecast replay does not reproduce the original portfolio")
        report[name] = summarize(result)
        (out / f"{name}-replay.json").write_text(json.dumps(result, allow_nan=False))
        print(name, json.dumps(report[name], ensure_ascii=False), flush=True)
    # Cost stress is a separate simulation; do not simply add costs to fixed trades.
    costs = [
        "spread_bps",
        "slippage_bps",
        "commission_per_share",
        "minimum_commission",
        "sell_fee_bps",
    ]
    for name, source, trace, mode in [variants[1], variants[4]]:
        cfg = {**source["config"], **{k: source["config"][k] * 1.5 for k in costs}}
        filt = ForecastReplay(trace, mode, (old if trace is old_trace else new)["model"])
        result = simulate(
            frame,
            StrategyConfig(**cfg),
            old["train_end"],
            old["validation_end"],
            source["strategies"],
            filt,
        )
        report[name + "-cost1.5"] = summarize(result)
    # Quantiles measure the actual rule candidates, not every model observation.
    for name, trace in [("legacy", old_trace), ("normalized", new_trace)]:
        points = pd.DataFrame(trace["market_curve"])
        valid = points[points.rule_candidate & points.probability.notna()]
        report[name + "-forecast-diagnostics"] = {
            "rule_candidate_minutes": int(points.rule_candidate.sum()),
            "valid_candidate_minutes": len(valid),
            "candidate_probability_quantiles": valid.probability.quantile(
                [0, 0.1, 0.5, 0.9, 1]
            ).to_dict(),
            "candidate_return_bps_quantiles": valid.expected_return_bps.quantile(
                [0, 0.1, 0.5, 0.9, 1]
            ).to_dict(),
            "model_statistics": trace.get("model_statistics"),
        }
    (out / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    )


if __name__ == "__main__":
    main()
