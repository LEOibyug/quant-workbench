"""Frozen pattern-model evaluation, with strictly pre-cutoff warmup and anchors."""

import json
from pathlib import Path

import pandas as pd
from quant_workbench.conditional_policy import artifact_digest
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.repository import Repository


def main():
    root = Path("artifacts/models/pattern-policy-v2")
    assert (root / "model.pt").exists()
    history_root = Path("artifacts/models/conditional-policy-v2/history")
    prior = pd.read_parquet(history_root / "daily.parquet")
    anchors = pd.read_parquet(history_root / "raw-anchor.parquet")
    training = json.loads((root / "training.json").read_text())
    if artifact_digest() != training["model_sha256"]:
        raise ValueError("模型摘要与冻结训练记录不一致")
    ds = Repository().get("datasets", "bfbd52245d674bd487bdd558295ad222")
    evaluation = Repository().load_dataset(ds["id"])
    assert prior.day.max() < "2025-09-01" and evaluation.day.min() >= "2025-09-01"
    if anchors.day.max() >= "2025-09-01":
        raise ValueError("预热对齐锚点必须在训练截止日前")
    pieces = []
    for symbol, g in prior.groupby("symbol"):
        g = g.sort_values("day").tail(127).copy()
        anchor = anchors[anchors.symbol == symbol].sort_values("day").iloc[-1]
        row = g[g.day == anchor.day].iloc[0]
        factor = anchor.close / row.close
        for k in ["open", "high", "low", "close"]:
            g[k] *= factor
        g["volume"] /= factor
        pieces.append(g)
    combined = pd.concat([*pieces, evaluation], ignore_index=True).sort_values(["day", "symbol"])
    repo = Repository()
    snapshot = repo.save_dataset(
        combined,
        "模式网络评价 · 历史预热+2025-09—2026-09",
        "alpaca-sip-raw-aligned-warmup",
        timeframe="1Day",
    )
    tasks = [
        (method, "legacy", multiplier)
        for method in [
            "pattern_policy",
            "spectral_rules",
            "generated_policy",
            "fixed_ensemble",
            "equal_weight",
        ]
        for multiplier in (1, 2)
    ]
    tasks.extend([("pattern_policy", "cost_aware", m) for m in (1, 2)])
    rows = []
    for method, policy, multiplier in tasks:
        config = PositionConfig(
            model=method, portfolio_policy=policy, tranche_weight=0.1, entry_band=0.005
        )
        costs = config.costs.model_dump()
        for k in [
            "spread_bps",
            "slippage_bps",
            "commission_per_share",
            "minimum_commission",
            "sell_fee_bps",
        ]:
            costs[k] *= multiplier
        config = PositionConfig(**{**config.model_dump(), "costs": costs})
        result = simulate_positions(combined, config, "2025-09-01", "2026-09-01", daily_bars=True)
        rows.append(
            dict(
                method=method,
                policy=policy,
                cost_multiplier=multiplier,
                config=result["config"],
                metrics=result["metrics"],
                contributions=result["contributions"],
                curve=[
                    {k: p[k] for k in ["date", "equity", "cash", "drawdown_pct"]}
                    for p in result["curve"]
                ],
            )
        )
        print(
            method,
            policy,
            multiplier,
            round(result["metrics"]["return_pct"], 3),
            round(result["metrics"]["max_drawdown_pct"], 3),
            flush=True,
        )
    report = dict(training=training, evaluation_dataset=ds, combined_dataset=snapshot, results=rows)
    Path("docs/research-results/2026-09-18-pattern-policy-v2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
