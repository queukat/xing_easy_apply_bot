from __future__ import annotations

import httpx
import pytest

from xingbot.xing.config import XINGRateLimitPolicy, XINGRetryPolicy
from xingbot.xing.http import (
    AsyncHttpTransport,
    HttpRetryExhausted,
    HttpRetryResult,
    XingHttpClient,
)


class StubTransport:
    def __init__(self, responses: list[Exception | httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, url: str, **_: object) -> httpx.Response:
        self.calls.append((method, url))
        if not self.responses:
            raise AssertionError("no responses configured")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        return None


def _make_response(status: int) -> httpx.Response:
    req = httpx.Request("GET", "https://example.com/test")
    return httpx.Response(status_code=status, request=req, json={"ok": status < 300})


def _make_client(transport: AsyncHttpTransport, attempts: int = 2) -> XingHttpClient:
    return XingHttpClient(
        transport=transport,
        retry=XINGRetryPolicy(
            max_attempts=attempts,
            base_delay_s=0.0,
            max_delay_s=0.0,
            backoff_factor=1.0,
            retry_statuses=(429, 500, 502, 503, 504),
        ),
        rate_limit=XINGRateLimitPolicy(min_interval_s=0.0, enabled=False),
    )


@pytest.mark.asyncio
async def test_xing_http_request_retries_on_request_error() -> None:
    transport = StubTransport(
        [
            httpx.RequestError("x", request=httpx.Request("GET", "https://example.com/test")),
            httpx.RequestError("x", request=httpx.Request("GET", "https://example.com/test")),
        ]
    )
    client = _make_client(transport, attempts=2)

    with pytest.raises(HttpRetryExhausted):
        await client.request("GET", "https://example.com/test")


@pytest.mark.asyncio
async def test_xing_http_request_retries_on_retry_status_until_success() -> None:
    transport = StubTransport([
        _make_response(429),
        _make_response(200),
    ])
    client = _make_client(transport, attempts=2)

    response = await client.request("GET", "https://example.com/test")

    assert response.status_code == 200
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_xing_http_request_json_raises_on_401() -> None:
    transport = StubTransport([_make_response(401)])
    client = _make_client(transport, attempts=1)

    with pytest.raises(httpx.HTTPStatusError):
        await client.request_json("GET", "https://example.com/test")


@pytest.mark.asyncio
async def test_xing_http_request_with_meta_tracks_retries() -> None:
    transport = StubTransport([_make_response(429), _make_response(200)])
    client = _make_client(transport, attempts=3)

    response, meta = await client.request_with_meta("GET", "https://example.com/test")

    assert isinstance(meta, HttpRetryResult)
    assert response.status_code == 200
    assert meta.attempts == 2
    assert meta.retries == 1
    assert meta.status_code == 200


@pytest.mark.asyncio
async def test_xing_http_respects_rate_limit_without_real_wait(monkeypatch) -> None:
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    class _FakeLoop:
        def __init__(self) -> None:
            self._ts = 100.0

        def time(self) -> float:
            return self._ts

    fake_loop = _FakeLoop()

    monkeypatch.setattr("xingbot.xing.http.asyncio.sleep", _sleep)
    monkeypatch.setattr("xingbot.xing.http.asyncio.get_running_loop", lambda: fake_loop)

    transport = StubTransport([_make_response(200), _make_response(200)])
    client = XingHttpClient(
        transport=transport,
        retry=XINGRetryPolicy(
            max_attempts=2,
            base_delay_s=0.0,
            max_delay_s=0.0,
            backoff_factor=1.0,
            retry_statuses=(429, 500),
        ),
        rate_limit=XINGRateLimitPolicy(min_interval_s=5.0, enabled=True),
    )

    await client.request("GET", "https://example.com/test")
    await client.request("GET", "https://example.com/test")

    assert sleeps == [5.0]
