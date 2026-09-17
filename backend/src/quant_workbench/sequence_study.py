"""Fixed regime/sequence candidate comparison with split-validation stability scoring."""

import json
from pathlib import Path

from quant_workbench.market_data import require_complete
from quant_workbench.models import ExperimentInput, StrategyConfig
from quant_workbench.research import begin_run, create_experiment, execute_run
from quant_workbench.study import render_report, training_diagnostics, validation_cost_stress


def stability_metrics(result):
    daily = result["daily_returns"]
    middle = len(daily) // 2
    if middle < 2 or len(daily) - middle < 2:
        raise ValueError("分段稳定性验证至少需要4个交易日")
    halves = []
    for part in (daily[:middle], daily[middle:]):
        capital = 1.0
        for day in part:
            capital *= 1 + day["return_pct"] / 100
        halves.append((capital - 1) * 100)
    return {
        "half_returns_pct": halves,
        "stability_score": min(halves) - 0.25 * result["metrics"]["max_drawdown_pct"],
    }


def stable_select(candidates):
    eligible = [
        c
        for c in candidates
        if c["status"] == "completed"
        and c["metrics"]["roundtrips"] >= 5
        and c["stability_score"] > 0
    ]
    return min(eligible, key=lambda c: (-c["stability_score"], c["name"])) if eligible else None


def run_sequence_study(
    repo,
    dataset_id,
    start,
    train_end,
    validation_end,
    end,
    symbols=None,
    output=None,
    include_test=False,
    progress=print,
):
    dataset = repo.get("datasets", dataset_id)
    symbols = symbols or dataset["symbols"]
    if not set(symbols).issubset(dataset["symbols"]):
        raise ValueError("研究标的不在数据集中")
    frame = repo.load_dataset(dataset_id)
    frame = frame[frame.symbol.isin(symbols)]
    train = require_complete(frame, start, train_end)
    validation = require_complete(frame, train_end, validation_end)
    if validation.timestamp.dt.tz_convert("America/New_York").dt.date.nunique() < 4:
        raise ValueError("分段稳定性验证至少需要4个交易日")
    base = StrategyConfig(initial_cash=100000 / len(symbols))
    legacy = {"sma", "opening_breakout", "vwap_reversion"}
    grid = [(strategy, "legacy", {}, "rule") for strategy in sorted(legacy)]
    standard = dict(
        fast=8,
        slow=21,
        stop_atr=2,
        take_atr=4,
        max_hold_minutes=45,
        reversion_bps=15,
        reversion_atr=1.5,
    )
    patient = dict(
        standard,
        stop_atr=2.5,
        take_atr=5,
        max_hold_minutes=60,
        cooldown_minutes=15,
        risk_per_trade_bps=20,
        max_daily_entries=3,
        reversion_atr=2,
    )
    for strategy in ("trend_pullback", "regime_adaptive"):
        grid.extend(
            [(strategy, "standard", standard, "rule"), (strategy, "patient", patient, "rule")]
        )
    grid.extend(
        [("regime_adaptive", "standard", standard, architecture) for architecture in ("mlp", "gru")]
    )
    report = dict(
        suite="sequence",
        dataset_id=dataset_id,
        dataset_sha256=dataset["sha256"],
        synthetic=dataset["synthetic"],
        source=dataset["source"],
        split=dict(start=start, train_end=train_end, validation_end=validation_end, end=end),
        cost_assumptions=base.model_dump(),
        diagnostics=training_diagnostics(train, base),
        selection_rule="min(first_half_return, second_half_return) - .25*max_drawdown; "
        ">0 and >=5 roundtrips else cash",
        candidate_grid=grid,
        symbols={},
    )
    dest = Path(output) if output else repo.root / "studies" / "sequence"
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "protocol.json").exists():
        raise ValueError("输出目录已有协议，请为独立研究使用新目录")

    def save(name):
        (dest / name).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    save("protocol.json")
    for symbol in symbols:
        candidates = []
        for strategy, variant, changes, architecture in grid:
            model = dict(
                enabled=architecture != "rule",
                architecture=(architecture if architecture != "rule" else "linear"),
                k=30,
                horizon=5,
                max_iter=3,
                cost_aware=True,
                cost_multiplier=1.5,
            )
            name = f"{symbol}/{strategy}/{variant}/{architecture}/h5"
            candidate = dict(
                name=name,
                strategy=strategy,
                architecture=architecture,
                horizon=5,
                mode="rule" if architecture == "rule" else "cost",
                status="failed",
                error=None,
                experiment_id=None,
            )
            try:
                experiment = create_experiment(
                    repo,
                    ExperimentInput(
                        name=name,
                        dataset_id=dataset_id,
                        symbols=[symbol],
                        start=start,
                        train_end=train_end,
                        validation_end=validation_end,
                        end=end,
                        config=base.model_copy(update={"strategy": strategy, **changes}),
                        model=model,
                    ),
                )
                candidate["experiment_id"] = experiment["id"]
                status = begin_run(repo, experiment["id"], "validation")
                execute_run(repo, experiment["id"], "validation", status["prior_test_exposure"])
                run = next(r for r in repo.runs(experiment["id"]) if r["phase"] == "validation")
                candidate.update(status=run["status"], error=run["error"])
                if run["status"] == "completed":
                    result = repo.result(experiment["id"], "validation")
                    candidate.update(
                        metrics=result["metrics"],
                        model_statistics=result["model_statistics"],
                        prior_test_exposure=result["prior_test_exposure"],
                        **stability_metrics(result),
                    )
            except ValueError as exc:
                candidate["status"] = "failed"
                candidate["error"] = str(exc)
            candidates.append(candidate)
            report["symbols"][symbol] = dict(
                candidates=candidates,
                selected=None,
                legacy_selected=None,
                test=None,
                legacy_test=None,
            )
            save("study.json")
            progress(f"{name}: {candidate['status']}", flush=True)
        item = report["symbols"][symbol]
        item["selected"] = stable_select(candidates)
        item["legacy_selected"] = stable_select([c for c in candidates if c["strategy"] in legacy])
        save("study.json")
    save("selection.json")
    validation_cost_stress(repo, report, progress)
    if include_test:
        for symbol, item in report["symbols"].items():
            for selected_key, result_key in (
                ("legacy_selected", "legacy_test"),
                ("selected", "test"),
            ):
                winner = item[selected_key]
                if winner is None:
                    item[result_key] = dict(policy="cash", return_pct=0)
                    continue
                identifier = winner["experiment_id"]
                status = begin_run(repo, identifier, "test")
                if status.get("launch"):
                    execute_run(repo, identifier, "test", status["prior_test_exposure"])
                run = next(r for r in repo.runs(identifier) if r["phase"] == "test")
                if run["status"] == "completed":
                    result = repo.result(identifier, "test")
                    item[result_key] = dict(
                        metrics=result["metrics"],
                        model_statistics=result["model_statistics"],
                        prior_test_exposure=result["prior_test_exposure"],
                    )
                else:
                    item[result_key] = dict(error=run["error"])
                progress(f"{symbol}: frozen {result_key} {run['status']}", flush=True)
    save("study.json")
    text = render_report(report).replace(
        "净收益率－0.5×最大回撤为评分", "验证前后半段较低收益率－0.25×最大回撤为评分"
    )
    text += "\n序列候选为因果卷积+双尺度GRU+注意力；每16个成熟样本以近期回放更新。\n"
    text += "分段收益与稳定性评分详见study.json。首2k分钟禁止模型入场。\n"
    (dest / "report.md").write_text(text)
    return dest
