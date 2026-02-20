from __future__ import annotations

import httpx
import pytest
import respx

from xingbot.xing.config import XINGRateLimitPolicy, XINGRetryPolicy
from xingbot.xing.http import HttpxTransport, XingHttpClient


def _new_client() -> XingHttpClient:
    return XingHttpClient(
        transport=HttpxTransport(timeout_s=2.0),
        retry=XINGRetryPolicy(
            max_attempts=2,
            base_delay_s=0.0,
            max_delay_s=0.0,
            backoff_factor=1.0,
            retry_statuses=(429, 500, 502, 503, 504),
        ),
        rate_limit=XINGRateLimitPolicy(min_interval_s=0.0, enabled=False),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_xing_http_integration_200() -> None:
    respx.get("https://xing.test/status/200").respond(status_code=200)
    client = _new_client()
    response = await client.request("GET", "https://xing.test/status/200")
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_xing_http_integration_401() -> None:
    respx.get("https://xing.test/status/401").respond(status_code=401)
    client = _new_client()
    response = await client.request("GET", "https://xing.test/status/401")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_xing_http_integration_403() -> None:
    respx.get("https://xing.test/status/403").respond(status_code=403)
    client = _new_client()
    response = await client.request("GET", "https://xing.test/status/403")
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_xing_http_integration_429_retry_and_fail_if_limit_exceeded() -> None:
    route = respx.get("https://xing.test/status/429")
    route.respond(status_code=429)
    client = XingHttpClient(
        transport=HttpxTransport(timeout_s=2.0),
        retry=XINGRetryPolicy(
            max_attempts=1,
            base_delay_s=0.0,
            max_delay_s=0.0,
            backoff_factor=1.0,
            retry_statuses=(429,),
        ),
        rate_limit=XINGRateLimitPolicy(min_interval_s=0.0, enabled=False),
    )
    response = await client.request("GET", "https://xing.test/status/429")
    assert response.status_code == 429


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_xing_http_integration_5xx() -> None:
    respx.get("https://xing.test/status/500").respond(status_code=500)
    client = _new_client()
    response = await client.request("GET", "https://xing.test/status/500")
    assert response.status_code == 500


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_xing_http_integration_request_json_raises_on_status() -> None:
    respx.get("https://xing.test/status/json").respond(status_code=500, json={"error": "x"})
    client = _new_client()
    with pytest.raises(httpx.HTTPStatusError):
        await client.request_json("GET", "https://xing.test/status/json")
