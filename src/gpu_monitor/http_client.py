"""Async HTTP client with retries, jitter, and polite rate-limiting."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

import httpx

from .config import AppConfig

logger = logging.getLogger(__name__)


class HttpClient:
    """
    Thin wrapper around httpx.AsyncClient with:
    - rotating user-agent
    - exponential backoff retry
    - configurable timeout
    - optional per-request delay (politeness)
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._ua_pool = list(config.user_agents)
        self._client: httpx.AsyncClient | None = None

    def _next_ua(self) -> str:
        return random.choice(self._ua_pool)

    def _build_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._next_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    async def __aenter__(self) -> "HttpClient":
        self._client = httpx.AsyncClient(
            timeout=self._config.http_timeout,
            follow_redirects=True,
            http2=True,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get(
        self,
        url: str,
        *,
        politeness_delay: float = 1.5,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("HttpClient not started. Use as async context manager.")

        headers = self._build_headers()
        if extra_headers:
            headers.update(extra_headers)

        last_exc: Exception | None = None
        for attempt in range(self._config.http_max_retries + 1):
            if attempt > 0:
                backoff = self._config.http_retry_backoff ** attempt
                jitter = random.uniform(0, backoff * 0.3)
                delay = backoff + jitter
                logger.debug("Retry %d for %s — waiting %.1fs", attempt, url, delay)
                await asyncio.sleep(delay)

            try:
                # Politeness delay before each request
                if attempt == 0 and politeness_delay > 0:
                    await asyncio.sleep(politeness_delay + random.uniform(0, 1.0))

                resp = await self._client.get(url, headers=headers)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning("Rate-limited by %s — sleeping %ds", url, retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status_code in (503, 502, 504):
                    logger.warning("Server error %d from %s", resp.status_code, url)
                    last_exc = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                    continue

                resp.raise_for_status()
                return resp

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning("Network error on %s (attempt %d): %s", url, attempt + 1, e)
                last_exc = e
            except httpx.HTTPStatusError as e:
                logger.warning("HTTP %d on %s", e.response.status_code, url)
                last_exc = e
                if e.response.status_code < 500:
                    raise  # Don't retry 4xx errors

        raise last_exc or RuntimeError(f"All retries failed for {url}")
