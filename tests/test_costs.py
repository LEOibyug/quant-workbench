import pytest
from quant_workbench.costs import estimate_round_trip
from quant_workbench.models import StrategyConfig
from quant_workbench.study import select_candidate


def test_roundtrip_estimate_accounts_for_size_and_minimum_commission():
    config = StrategyConfig(spread_bps=2, slippage_bps=2, sell_fee_bps=0.3)
    small = estimate_round_trip(100, 1000, 10000, config)
    assert small["quantity"] == 10
    # $0.60 spread/slippage + $2 min fees + $0.029991 sell fee / $1000.
    assert small["round_trip_bps"] == pytest.approx(26.29991)
    large = estimate_round_trip(100, 100000, 100000, config)
    assert large["round_trip_bps"] < small["round_trip_bps"]
    assert estimate_round_trip(100, 0, 100000, config)["round_trip_bps"] is None


def test_validation_selection_can_choose_cash_and_ignores_test_metrics():
    candidate = {
        "name": "a",
        "status": "completed",
        "metrics": {
            "return_pct": -0.1,
            "max_drawdown_pct": 0.1,
            "roundtrips": 10,
            "trade_count": 20,
        },
        "test_metrics": {"return_pct": 100},
    }
    assert select_candidate([candidate]) is None
    candidate["metrics"]["return_pct"] = 1
    assert select_candidate([candidate]) is candidate


def test_study_retains_rules_and_report_when_model_training_is_not_possible(tmp_path):
    import json

    import pandas as pd
    from quant_workbench.market_data import session_minutes
    from quant_workbench.repository import Repository
    from quant_workbench.study import run_study

    repo = Repository(tmp_path / "data")
    times = session_minutes("2024-01-02", "2024-01-05")
    frame = pd.DataFrame(
        {
            "timestamp": times,
            "symbol": "TEST",
            "open": 100,
            "high": 100,
            "low": 100,
            "close": 100,
            "volume": 10000,
        }
    )
    dataset = repo.save_dataset(frame, "constant", "synthetic", True)
    dest = run_study(
        repo,
        dataset["id"],
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        output=tmp_path / "report",
        progress=lambda *a, **k: None,
    )
    report = json.loads((dest / "study.json").read_text())
    candidates = report["symbols"]["TEST"]["candidates"]
    assert len(candidates) == 12
    assert sum(c["status"] == "completed" for c in candidates) == 3
    assert report["symbols"]["TEST"]["selected"] is None
    assert (dest / "report.md").exists()
