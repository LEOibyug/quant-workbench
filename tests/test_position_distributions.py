import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig, simulate_positions

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from research_distribution_book import ResearchDistributionBook  # noqa: E402


class Marks:
    def at(self, day, symbols, field):
        return {s: 80.0 for s in symbols}


def test_real_engine_distribution_conserves_equity_pnl_and_avoids_false_exit():
    days = schedule("2024-04-01", "2024-04-10").index.strftime("%Y-%m-%d").tolist()
    event_day = days[3]
    prices = [100.0 if day < event_day else 80.0 for day in days]
    frame = pd.DataFrame(
        dict(day=days, symbol="P", open=prices, high=prices, low=prices, close=prices, volume=1e9)
    )
    cfg = PositionConfig(
        model="fixed_ensemble", rebalance_days=1, max_drawdown_pct=2, stop_loss_pct=2
    )
    cfg = cfg.model_copy(
        update={
            "costs": cfg.costs.model_copy(
                update={
                    "spread_bps": 0,
                    "slippage_bps": 0,
                    "commission_per_share": 0,
                    "minimum_commission": 0,
                    "sell_fee_bps": 0,
                }
            )
        }
    )
    mapping = {(d, "P"): dict(target_weight=0.2, volatility=0.01, status="ok") for d in days}
    event = dict(
        id="split", parent="P", child="C", day=event_day, numerator=1, denominator=4, verified=True
    )
    book = ResearchDistributionBook([event], Marks())
    with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
        raw = simulate_positions(frame, cfg, days[0], "2024-04-10", daily_bars=True)
        corrected = simulate_positions(
            frame, cfg, days[0], "2024-04-10", daily_bars=True, research_distributions=book
        )
    assert raw["metrics"]["halted"]
    assert not corrected["metrics"]["halted"]
    for p in corrected["curve"]:
        assert p["equity"] == pytest.approx(cfg.costs.initial_cash)
        assert p["equity"] - cfg.costs.initial_cash == pytest.approx(
            p["realized_pnl"] + p["unrealized_pnl"]
        )
        assert p["equity"] == pytest.approx(
            p["cash"]
            + sum(a["market_value"] for a in p["assets"].values())
            + p["distributed_assets"]["market_value"]
        )
    assert sum(r["net_profit"] for r in corrected["contributions"]) == pytest.approx(0)
    assert corrected["metrics"]["estimated_liquidation_return_pct"] is None
    assert "C" not in corrected["positions"]
    assert corrected["curve"][3]["cash"] == corrected["curve"][2]["cash"]
    assert corrected["research_distributions"]["events"][0]["parent_shares"] > 0
    with patch("quant_workbench.position.daily_forecasts", return_value=mapping):
        with pytest.raises(ValueError, match="reused"):
            simulate_positions(
                frame, cfg, days[0], "2024-04-10", daily_bars=True, research_distributions=book
            )
