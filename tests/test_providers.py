"""Provider contract checks with mocked HTTP, never real account credentials."""

import httpx
import pytest
from quant_workbench import providers
from quant_workbench.models import ProviderInput


def request(provider):
    return ProviderInput(provider=provider, symbols=["AAPL"], start="2024-01-03", end="2024-01-04")


def mock_client(monkeypatch, handler):
    client_type = httpx.Client
    monkeypatch.setattr(
        providers.httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_alpaca_pages_shift_start_to_end_and_filter_extended_hours(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "test-id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test-secret")
    calls = []

    def handler(req):
        calls.append(req)
        bar = {"t": "2024-01-03T14:30:00Z", "o": 100, "h": 101, "l": 99, "c": 100, "v": 50}
        if "page_token" not in req.url.params:
            return httpx.Response(200, json={"bars": {"AAPL": [bar]}, "next_page_token": "next"})
        bar["t"] = "2024-01-03T21:00:00Z"
        return httpx.Response(200, json={"bars": {"AAPL": [bar]}})

    mock_client(monkeypatch, handler)
    frame = providers.fetch_provider(request("alpaca"))
    assert len(calls) == 2
    assert calls[0].url.params["adjustment"] == "raw"
    assert frame.timestamp.iloc[0].isoformat() == "2024-01-03T14:31:00+00:00"
    assert len(frame) == 1


def test_massive_pagination_and_cross_origin_guard(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    calls = []
    malicious = False

    def handler(req):
        calls.append(req)
        assert req.headers["Authorization"] == "Bearer test-key"
        if "cursor" not in req.url.params:
            next_url = (
                "https://attacker.invalid/leak"
                if malicious
                else f"https://api.massive.com{req.url.path}?cursor=next"
            )
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "results": [
                        {"t": 1704292200000, "o": 100, "h": 101, "l": 99, "c": 100, "v": 50}
                    ],
                    "next_url": next_url,
                },
            )
        return httpx.Response(200, json={"status": "OK", "results": []})

    mock_client(monkeypatch, handler)
    frame = providers.fetch_provider(request("massive"))
    assert len(calls) == 2
    assert len(frame) == 1
    assert frame.timestamp.iloc[0].isoformat() == "2024-01-03T14:31:00+00:00"
    malicious = True
    calls.clear()
    with pytest.raises(ValueError, match="分页地址"):
        providers.fetch_provider(request("massive"))
    assert len(calls) == 1


def test_provider_errors_are_sanitized(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "never-display-this")
    mock_client(monkeypatch, lambda req: httpx.Response(429, text="secret=never-display-this"))
    with pytest.raises(ValueError, match="调用频率") as exc:
        providers.fetch_provider(request("massive"))
    assert "never-display-this" not in str(exc.value)


def test_transient_transport_retries_same_page_without_duplicate_bars(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "test-id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test-secret")
    monkeypatch.setattr(providers.time, "sleep", lambda _: None)
    calls = []

    def handler(req):
        calls.append(req.url)
        if len(calls) < 3:
            raise httpx.ConnectError("transient TLS failure", request=req)
        return httpx.Response(
            200,
            json={
                "bars": {
                    "AAPL": [
                        {"t": "2024-01-03T14:30Z", "o": 100, "h": 101, "l": 99, "c": 100, "v": 50}
                    ]
                }
            },
        )

    mock_client(monkeypatch, handler)
    frame = providers.fetch_provider(request("alpaca"))
    assert len(calls) == 3 and len(set(calls)) == 1 and len(frame) == 1
