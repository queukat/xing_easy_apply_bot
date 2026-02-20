from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

import httpx

from xingbot.logging import logger
from xingbot.xing.config import XINGRateLimitPolicy, XINGRetryPolicy


@dataclass(frozen=True)
class HttpRetryResult:
    attempts: int
    retries: int
    status_code: int | None


class AsyncHttpTransport(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        ...

    async def close(self) -> None:
        ...


class HttpTransportError(RuntimeError):
    """Base error for network transport failures."""


class HttpRetryExhausted(HttpTransportError):
    """Raised when request retries are exhausted."""


class SimpleAsyncRateLimiter:
    """Deterministic fixed-interval rate limiter."""

    def __init__(self, policy: XINGRateLimitPolicy) -> None:
        self._policy = policy
        self._next_ts = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self._policy.enabled or self._policy.min_interval_s <= 0:
            return

        async with self._lock:
            now = asyncio.get_running_loop().time()
            delay = self._next_ts - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_ts = max(self._next_ts, now) + self._policy.min_interval_s


class HttpxTransport:
    def __init__(
        self,
        timeout_s: float = 10.0,
        user_agent: str | None = None,
        proxy: str | None = None,
    ) -> None:
        timeout = httpx.Timeout(timeout_s)
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "follow_redirects": True,
            "headers": {"User-Agent": user_agent} if user_agent else None,
        }

        if proxy:
            try:
                # Newer httpx uses `proxy=...`.
                self._client = httpx.AsyncClient(proxy=proxy, **client_kwargs)
            except TypeError:
                # Compatibility with older httpx that still exposes `proxies=...`.
                self._client = httpx.AsyncClient(
                    proxies={"all://": proxy},
                    **client_kwargs,
                )
        else:
            self._client = httpx.AsyncClient(**client_kwargs)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return await self._client.request(method, url, **kwargs)

    async def close(self) -> None:
        await self._client.aclose()


class XingHttpClient:
    def __init__(
        self,
        *,
        transport: AsyncHttpTransport,
        retry: XINGRetryPolicy,
        rate_limit: XINGRateLimitPolicy,
    ) -> None:
        self._transport = transport
        self._retry = retry
        self._rate_limiter = SimpleAsyncRateLimiter(rate_limit)

    @staticmethod
    def _is_retry_status(status: int, retry_statuses: Sequence[int]) -> bool:
        return status in retry_statuses

    @staticmethod
    def _retry_after(headers: Mapping[str, Any], fallback: float) -> float:
        raw = headers.get("retry-after")
        if not raw:
            return 0.0
        value = str(raw).strip()
        if not value:
            return 0.0
        try:
            return float(value)
        except ValueError:
            return 0.0

    @staticmethod
    def _jittered_sleep(base: float, max_delay: float) -> float:
        if base <= 0:
            return 0.0
        jitter = base * 0.2
        value = random.uniform(max(0.0, base - jitter), base + jitter)
        return min(max_delay, value)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        retry_statuses = self._retry.retry_statuses

        for attempt in range(1, self._retry.max_attempts + 1):
            await self._rate_limiter.wait()
            try:
                response = await self._transport.request(method=method, url=url, **kwargs)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= self._retry.max_attempts:
                    raise HttpRetryExhausted(
                        f"request failed after {attempt} attempts: {url}"
                    ) from exc

                delay = self._jittered_sleep(
                    self._retry.base_delay_s * (self._retry.backoff_factor ** (attempt - 1)),
                    self._retry.max_delay_s,
                )
                logger.warning(
                    "[http] request error on {} {}: {}; retrying in {:.2f}s ({}/{})",
                    method,
                    url,
                    exc,
                    delay,
                    attempt,
                    self._retry.max_attempts,
                )
                await asyncio.sleep(delay)
                continue

            if self._is_retry_status(response.status_code, retry_statuses):
                if attempt >= self._retry.max_attempts:
                    return response

                delay = self._retry_after(response.headers, 0.0)
                if not delay:
                    delay = self._jittered_sleep(
                        self._retry.base_delay_s * (self._retry.backoff_factor ** (attempt - 1)),
                        self._retry.max_delay_s,
                    )

                logger.warning(
                    "[http] retryable status {} on {} {}: retrying in {:.2f}s ({}/{})",
                    response.status_code,
                    method,
                    url,
                    delay,
                    attempt,
                    self._retry.max_attempts,
                )
                await asyncio.sleep(delay)
                continue

            return response

        if last_error:
            raise HttpRetryExhausted(
                f"request failed after {self._retry.max_attempts} attempts: {url}"
            ) from last_error
        return response

    async def request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.request(method, url, **kwargs)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload

    async def close(self) -> None:
        await self._transport.close()

    async def request_with_meta(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> tuple[httpx.Response, HttpRetryResult]:
        retries = 0
        last_code: int | None = None

        last_error: Exception | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            await self._rate_limiter.wait()
            try:
                response = await self._transport.request(method=method, url=url, **kwargs)
                last_code = response.status_code
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= self._retry.max_attempts:
                    raise HttpRetryExhausted(
                        f"request failed after {attempt} attempts: {url}"
                    ) from exc
                retries += 1
                delay = self._jittered_sleep(
                    self._retry.base_delay_s * (self._retry.backoff_factor ** (attempt - 1)),
                    self._retry.max_delay_s,
                )
                await asyncio.sleep(delay)
                continue

            if self._is_retry_status(response.status_code, self._retry.retry_statuses):
                retries += 1
                if attempt >= self._retry.max_attempts:
                    return response, HttpRetryResult(attempts=attempt, retries=retries, status_code=last_code)
                delay = self._retry_after(response.headers, 0.0) or self._jittered_sleep(
                    self._retry.base_delay_s * (self._retry.backoff_factor ** (attempt - 1)),
                    self._retry.max_delay_s,
                )
                await asyncio.sleep(delay)
                continue

            return response, HttpRetryResult(attempts=attempt, retries=retries, status_code=last_code)

        if last_error is not None:
            raise HttpRetryExhausted(
                f"request failed after {self._retry.max_attempts} attempts: {url}"
            ) from last_error
        return response, HttpRetryResult(attempts=self._retry.max_attempts, retries=retries, status_code=last_code)


__all__ = [
    "AsyncHttpTransport",
    "HttpRetryExhausted",
    "HttpRetryResult",
    "HttpTransportError",
    "HttpxTransport",
    "SimpleAsyncRateLimiter",
    "XingHttpClient",
]
