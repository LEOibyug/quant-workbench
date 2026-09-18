import httpx
import pandas as pd
import pytest
from quant_workbench.daily_providers import fetch_daily
from quant_workbench.models import ProviderInput
from quant_workbench.position import PositionConfig, simulate_positions
from quant_workbench.simulations import SimulationInput


@pytest.mark.parametrize("provider", ["alpaca", "massive"])
def test_daily_provider_pagination_and_exclusive_end(monkeypatch, provider):
    monkeypatch.setenv("APCA_API_KEY_ID", "test")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test")
    monkeypatch.setenv("MASSIVE_API_KEY", "test")
    calls = []

    def get(client, url, **kwargs):
        calls.append((url, kwargs))
        bars = [dict(t="2024-01-02T05:00:00Z", o=100, h=101, l=99, c=100, v=10000)]
        if provider == "alpaca":
            assert kwargs["params"]["timeframe"] == "1Day"
            if len(calls) == 2:
                bars[0]["t"] = "2024-01-03T05:00:00Z"
            body = {"bars": {"TEST": bars}, "next_page_token": "next" if len(calls) == 1 else None}
        else:
            assert "/range/1/day/" in url
            bars[0]["t"] = int(pd.Timestamp(bars[0]["t"]).timestamp() * 1000)
            body = {"status": "OK", "results": bars}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr("quant_workbench.daily_providers._get", get)
    result = fetch_daily(ProviderInput(
        provider=provider, symbols=["TEST"], start="2024-01-02", end="2024-01-03",
    ))
    assert result.day.tolist() == ["2024-01-02"]
    assert len(calls) == (2 if provider == "alpaca" else 1)


def test_daily_volume_is_causal_and_missing_days_are_not_fabricated():
    frame = pd.DataFrame(dict(
        day=["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], symbol="TEST",
        open=100.0, high=101.0, low=99.0, close=100.0, volume=390000.0,
    ))
    cfg = PositionConfig(model="equal_weight")
    baseline = simulate_positions(frame, cfg, "2024-01-02", "2024-01-06", daily_bars=True)
    frame.loc[frame.day == "2024-01-04", "volume"] *= 100
    changed = simulate_positions(frame, cfg, "2024-01-02", "2024-01-06", daily_bars=True)
    assert [t for t in baseline["trades"] if t["date"] <= "2024-01-04"] == [
        t for t in changed["trades"] if t["date"] <= "2024-01-04"
    ]
    with pytest.raises(ValueError, match="缺少交易日日线"):
        simulate_positions(frame.iloc[1:], cfg, "2024-01-02", "2024-01-06", daily_bars=True)
    request = SimulationInput(
        source_id="a" * 32, symbol="TEST", start="2024-01-01", end="2025-01-01",
    )
    assert (request.end - request.start).days == 366
