"""Bounded, reproducible validation search; final test evaluated only after selection."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from quant_workbench.costs import estimate_round_trip
from quant_workbench.engine import simulate
from quant_workbench.market_data import require_complete
from quant_workbench.models import ExperimentInput, StrategyConfig
from quant_workbench.profiles import analyze_stocks
from quant_workbench.research import begin_run, create_experiment, execute_run


def training_diagnostics(frame, config):
    profiles = analyze_stocks(frame)
    for profile in profiles:
        group = frame[frame.symbol == profile["symbol"]].copy()
        day = group.timestamp.dt.tz_convert("America/New_York").dt.date
        returns = group.groupby(day).close.pct_change().dropna() * 10000
        price = float(group.close.median())
        volume = float(group.volume.median())
        estimate = estimate_round_trip(price, volume, config.initial_cash, config)
        cost = estimate["round_trip_bps"]
        profile.update(
            {
                "median_price": price,
                "median_minute_volume": volume,
                "up_fraction": float((returns > 0).mean()),
                "median_absolute_return_bps": float(returns.abs().median()),
                "p90_absolute_return_bps": float(returns.abs().quantile(0.9)),
                "estimated_quantity": estimate["quantity"],
                "estimated_round_trip_bps": cost,
                "fraction_return_exceeds_cost": float((returns > cost).mean()) if cost else None,
            }
        )
    return profiles


def select_candidate(candidates):
    # Cash is a genuine candidate: do not force a negative-net strategy to trade.
    valid = [c for c in candidates if c["status"] == "completed"]
    active = [c for c in valid if c["metrics"]["roundtrips"] >= 5]
    ranked = sorted(
        active,
        key=lambda c: (
            -(c["metrics"]["return_pct"] - 0.5 * c["metrics"]["max_drawdown_pct"]),
            c["metrics"]["trade_count"],
            c["name"],
        ),
    )
    if (
        not ranked
        or ranked[0]["metrics"]["return_pct"] - 0.5 * ranked[0]["metrics"]["max_drawdown_pct"] <= 0
    ):
        return None
    return ranked[0]


def run_study(
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
    suite="legacy",
):
    dataset = repo.get("datasets", dataset_id)
    symbols = symbols or dataset["symbols"]
    frame = repo.load_dataset(dataset_id)
    if not set(symbols).issubset(dataset["symbols"]):
        raise ValueError("研究标的不在数据集中")
    frame = frame[frame.symbol.isin(symbols)]
    # Validation checks and diagnostics never calculate test statistics.
    train = require_complete(frame, start, train_end)
    require_complete(frame, train_end, validation_end)
    budget = 100_000 / len(symbols)
    config = StrategyConfig(initial_cash=budget)
    report = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_id": dataset_id,
        "dataset_sha256": dataset["sha256"],
        "synthetic": dataset["synthetic"],
        "source": dataset["source"],
        "split": {
            "start": start,
            "train_end": train_end,
            "validation_end": validation_end,
            "end": end,
        },
        "cost_assumptions": config.model_dump(),
        "selection_rule": (
            "validation return_pct - 0.5 * max_drawdown_pct; >=5 roundtrips; cash if score<=0"
        ),
        "diagnostics": training_diagnostics(train, config),
        "suite": suite,
        "symbols": {},
    }
    dest = Path(output) if output else repo.root / "studies" / report["id"]
    dest.mkdir(parents=True, exist_ok=True)
    # Declare architecture and horizon before evaluating any candidate.
    if suite == "enhanced":
        grid = [
            (strategy, "rule", 1.5, "linear", 1)
            for strategy in ("sma", "opening_breakout", "vwap_reversion")
        ]
        grid += [
            (strategy, mode, 1.5, architecture, horizon)
            for strategy in ("trend_breakout", "range_reversion")
            for mode, architecture, horizon in (
                ("rule", "linear", 1),
                ("cost", "linear", 5),
                ("cost", "mlp", 5),
                ("cost", "mlp", 15),
            )
        ]
    elif suite == "legacy":
        grid = [
            (strategy, mode, multiplier, "linear", 1)
            for strategy in ("sma", "opening_breakout", "vwap_reversion")
            for mode, multiplier in (
                ("rule", 1.5),
                ("probability", 1.5),
                ("cost", 1.0),
                ("cost", 1.5),
            )
        ]
    else:
        raise ValueError("未知研究候选集")
    report["candidate_grid"] = grid
    (dest / "protocol.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for symbol in symbols:
        candidates = []
        for strategy, mode, multiplier, architecture, horizon in grid:
            name = f"{symbol}/{strategy}/{mode}/{multiplier:g}/{architecture}/h{horizon}"
            request = ExperimentInput(
                name=name,
                dataset_id=dataset_id,
                symbols=[symbol],
                start=start,
                train_end=train_end,
                validation_end=validation_end,
                end=end,
                config=config.model_copy(update={"strategy": strategy}),
                model={
                    "enabled": mode != "rule",
                    "k": 30,
                    "architecture": architecture,
                    "horizon": horizon,
                    "cost_aware": mode == "cost",
                    "cost_multiplier": multiplier,
                    "min_edge_bps": 1,
                },
            )
            candidate = {
                "name": name,
                "experiment_id": None,
                "mode": mode,
                "strategy": strategy,
                "architecture": architecture,
                "horizon": horizon,
                "cost_multiplier": multiplier,
                "status": "failed",
                "error": None,
            }
            try:
                experiment = create_experiment(repo, request)
                candidate["experiment_id"] = experiment["id"]
                status = begin_run(repo, experiment["id"], "validation")
                execute_run(repo, experiment["id"], "validation", status["prior_test_exposure"])
                run = repo.runs(experiment["id"])[0]
                candidate.update({"status": run["status"], "error": run["error"]})
                if run["status"] == "completed":
                    result = repo.result(experiment["id"], "validation")
                    candidate.update(
                        {
                            "metrics": result["metrics"],
                            "model_statistics": result["model_statistics"],
                            "prior_test_exposure": result["prior_test_exposure"],
                        }
                    )
            except ValueError as exc:
                candidate["error"] = str(exc)
            candidates.append(candidate)
            report["symbols"][symbol] = {"candidates": candidates, "selected": None, "test": None}
            (dest / "study.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            progress(f"{name}: {candidate['status']}", flush=True)
        selected = select_candidate(candidates)
        report["symbols"][symbol] = {
            "candidates": candidates,
            "selected": selected,
            "test": None,
            "legacy_selected": select_candidate(
                [
                    c
                    for c in candidates
                    if c["strategy"] in {"sma", "opening_breakout", "vwap_reversion"}
                ]
            ),
            "legacy_test": None,
        }
        (dest / "study.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    # Freeze all selections before any final test is revealed.
    (dest / "selection.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validation_cost_stress(repo, report, progress)
    if include_test:
        for symbol, item in report["symbols"].items():
            if suite == "enhanced":
                legacy = item["legacy_selected"]
                if legacy is None:
                    item["legacy_test"] = {"policy": "cash", "return_pct": 0}
                else:
                    legacy_id = legacy["experiment_id"]
                    status = begin_run(repo, legacy_id, "test")
                    if status.get("launch"):
                        execute_run(repo, legacy_id, "test", status["prior_test_exposure"])
                    legacy_run = next(r for r in repo.runs(legacy_id) if r["phase"] == "test")
                    item["legacy_test"] = (
                        {"metrics": repo.result(legacy_id, "test")["metrics"]}
                        if legacy_run["status"] == "completed"
                        else {"error": legacy_run["error"]}
                    )
            if item["selected"] is None:
                item["test"] = {
                    "policy": "cash",
                    "return_pct": 0,
                    "note": "No validation-qualified strategy",
                }
                continue
            identifier = item["selected"]["experiment_id"]
            status = begin_run(repo, identifier, "test")
            if status.get("launch"):
                execute_run(repo, identifier, "test", status["prior_test_exposure"])
            run = next(r for r in repo.runs(identifier) if r["phase"] == "test")
            if run["status"] == "completed":
                result = repo.result(identifier, "test")
                item["test"] = {
                    "metrics": result["metrics"],
                    "model_statistics": result["model_statistics"],
                    "prior_test_exposure": result["prior_test_exposure"],
                }
            else:
                item["test"] = {"error": run["error"]}
            progress(f"{symbol}: selected final test {run['status']}", flush=True)
    (dest / "study.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (dest / "report.md").write_text(render_report(report), encoding="utf-8")
    return dest


def validation_cost_stress(repo, report, progress=print):
    """Re-run frozen selections on validation only, without changing the selection."""
    cost_fields = (
        "spread_bps",
        "slippage_bps",
        "commission_per_share",
        "minimum_commission",
        "sell_fee_bps",
    )
    for symbol, item in report["symbols"].items():
        selected = item["selected"]
        item["cost_stress"] = []
        if selected is None:
            continue
        experiment = repo.get("experiments", selected["experiment_id"])
        frame = repo.load_dataset(experiment["dataset_id"])
        frame = frame[frame.symbol == symbol]
        for factor in (1.5, 2.0):
            config = StrategyConfig(
                **{
                    **experiment["config"],
                    **{key: experiment["config"][key] * factor for key in cost_fields},
                }
            )
            model = (
                repo.load_model(experiment["id"], experiment["model_artifact"])
                if experiment["model"]["enabled"]
                else None
            )
            try:
                result = simulate(
                    frame,
                    config,
                    experiment["train_end"],
                    experiment["validation_end"],
                    experiment["strategies"],
                    model,
                )
                item["cost_stress"].append({"factor": factor, "metrics": result["metrics"]})
            except ValueError as exc:
                item["cost_stress"].append({"factor": factor, "error": str(exc)})
            progress(f"{symbol}: validation cost stress {factor:g}x", flush=True)


def render_report(report):
    synthetic = report["synthetic"]
    lines = [
        "# 成本约束策略与预测模型研究",
        "",
        f"数据来源：{report['source']}。",
        "**仅为合成行情流程验证，不代表这些真实股票的特征或策略盈利能力。**"
        if synthetic
        else "非合成标记数据；来源真实性与覆盖范围仍以供应商或导入数据核验为准。",
        "",
        f"时间分段：{report['split']}（右端不含）。",
        "",
        "成本假设固定：完整价差2bps、单边滑点2bps、佣金0.005美元/股、最低1美元/笔、卖出规费0.3bps。",
        "固定候选集合见protocol.json；k=30、上涨概率门槛0.55、成本安全倍数与跨度在验证前冻结。",
        "每股独立资金；仅验证区间选型，净收益率－0.5×最大回撤为评分，至少5个完整交易，无正评分则持币。",
        "所有标的选择先写入selection.json，再允许最终测试；已有测试暴露会单独标识。",
        "",
        "## 开发期数据诊断",
        "",
        "| 标的 | 分钟波动中位数 bps | 往返成本 bps | 超成本正收益占比 | 趋势效率 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for p in report["diagnostics"]:
        cost = p["estimated_round_trip_bps"]
        rate = p["fraction_return_exceeds_cost"]
        lines.append(
            (
                f"| {p['symbol']} | {p['median_absolute_return_bps']:.2f} | "
                f"{cost:.2f} | {rate:.2%} | {p['trend_efficiency']:.3f} |"
            )
            if cost is not None and rate is not None
            else f"| {p['symbol']} | — | 不可成交 | — | — |"
        )
    lines += ["", "成本由开发期中位价格、成交量与预算估算，并非盘口实测；不能据此认定成交可盈利。"]
    cost_candidates = [
        c
        for item in report["symbols"].values()
        for c in item["candidates"]
        if c["mode"] == "cost" and c["status"] == "completed"
    ]
    if cost_candidates and all(c["metrics"]["trade_count"] == 0 for c in cost_candidates):
        lines += [
            "",
            "**本轮所有成本过滤候选均无交易：收益幅度预测不足以覆盖设置的费用门槛。**",
            "这表示当前收益预测方案没有找到满足成本约束的入场机会，不能解释为真实市场没有机会。",
            "以下验证选中的概率/规则方案虽计入实际费用，但并未通过上述收益门槛，须分别理解。",
        ]
    for symbol, item in report["symbols"].items():
        lines += [
            "",
            f"## {symbol}",
            "",
            "| 候选 | 验证净收益 % | 回撤 % | 完整交易 | 模型 Brier | 收益 MAE bps |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for c in item["candidates"]:
            if c["status"] != "completed":
                lines.append(f"| {c['name']} | 失败：{c['error']} | — | — | — | — |")
                continue
            m, s = c["metrics"], c["model_statistics"]
            brier = f"{s['brier_score']:.4f}" if s.get("brier_score") is not None else "—"
            mae = f"{s['return_mae_bps']:.2f}" if s.get("return_mae_bps") is not None else "—"
            lines.append(
                f"| {c['name']} | {m['return_pct']:.3f} | {m['max_drawdown_pct']:.3f} | "
                f"{m['roundtrips']} | {brier} | {mae} |"
            )
        if any(c.get("prior_test_exposure") for c in item["candidates"]):
            lines += ["", "**范围存在历史测试暴露，本轮选型只能视为探索性研究。**"]
        winner = item["selected"]
        lines += ["", f"验证选择：{winner['name'] if winner else '持币，不交易'}。"]
        for stress in item.get("cost_stress", []):
            if "metrics" in stress:
                lines += [
                    f"验证成本×{stress['factor']:g}：净收益 "
                    f"{stress['metrics']['return_pct']:.3f}%，"
                    f"回撤 {stress['metrics']['max_drawdown_pct']:.3f}%。"
                ]
            else:
                lines += [f"验证成本×{stress['factor']:g}：{stress['error']}。"]
        if winner and winner.get("model_statistics"):
            scores = winner["model_statistics"]
            lines += [
                f"模型验证 Brier {scores['brier_score']:.5f}，固定训练比例基线 "
                f"{scores['baseline_brier_score']:.5f}；预测收益 MAE "
                f"{scores['return_mae_bps']:.3f}bps，零收益基线 "
                f"{scores['zero_return_mae_bps']:.3f}bps。"
            ]
        control = item.get("legacy_test")
        if control:
            control_return = control.get("metrics", {}).get("return_pct", control.get("return_pct"))
            lines += [f"旧规则对照测试净收益：{control_return}%。"]
        test = item["test"]
        if test and "metrics" in test:
            lines += [
                f"冻结方案测试净收益 {test['metrics']['return_pct']:.3f}%，"
                f"回撤 {test['metrics']['max_drawdown_pct']:.3f}%。",
                f"该日期是否已有测试暴露：{test['prior_test_exposure']}。",
            ]
        elif test:
            lines += [f"最终阶段：{test}。"]
    lines += [
        "",
        "## 解释限制",
        "",
        "线性/RBF双头使用逻辑分类与Huber回归；MLP使用两个64→32网络与延迟成熟的预测/真实值/误差反馈。",
        "首2k周期不入场，逐股独立在线更新，标准化仅开发期拟合。h分钟收盘预测不等于实际成交净利润。",
        "成本门槛采用当前已结束分钟的价格/成交量估算，实际成交仍在下一分钟；碎单最低佣金和跳空会增加成本。",
        "多个候选重复验证仍可能过拟合；单次新测试不能证明持续盈利，不据此自动发布实盘策略。",
    ]
    return "\n".join(lines) + "\n"
