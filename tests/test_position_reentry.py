"""Research restart preserves global loss history and next-open execution."""
import pytest
from test_dividend_position import setup
from quant_workbench.position import simulate_positions


def test_restart_resets_only_risk_episode_after_liquidation():
    frame, config, _ = setup()
    args = frame, config, '2024-01-02', '2024-01-12'
    original = simulate_positions(*args, daily_bars=True)
    disabled = simulate_positions(*args, daily_bars=True, research_reentry=lambda day: False)
    for field in ['metrics', 'trades', 'contributions', 'curve']:
        assert original[field] == disabled[field]
    assert original['metrics']['halted']
    resumed = simulate_positions(*args, daily_bars=True, research_reentry=lambda day: True)
    events = [e for e in resumed['research_reentry'] if e['restart']]
    assert events
    event = events[0]
    point = next(p for p in resumed['curve'] if p['date'] == event['date'])
    assert not any(point['positions'].values())
    assert point['drawdown_pct'] > config.max_drawdown_pct
    buys = [t for t in resumed['trades'] if t['side'] == 'buy' and t['date'] > event['date']]
    assert buys and buys[0]['signal_date'] == event['date']
    peak = config.costs.initial_cash
    for point in resumed['curve']:
        peak = max(peak, point['equity'])
        assert point['drawdown_pct'] == pytest.approx((1-point['equity']/peak)*100)
