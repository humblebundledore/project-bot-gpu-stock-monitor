"""
Async scheduler: runs all retailer scrapers in a loop with jitter.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, time as dtime
from typing import Callable, Coroutine, Any

from .alerting import Alerter
from .browser import BrowserClient
from .config import AppConfig
from .db import Database
from .http_client import HttpClient
from .retailers import RETAILER_MAP, BaseRetailer

logger = logging.getLogger(__name__)


async def run_single_retailer(
    retailer: BaseRetailer,
    db: Database,
    alerter: Alerter,
    config: AppConfig,
) -> None:
    """Scrape one retailer and process alerts for all discovered products."""
    logger.info("[%s] Starting scrape", retailer.name)
    try:
        products = await retailer.scrape()
    except Exception as e:
        logger.error("[%s] Scrape failed: %s", retailer.name, e, exc_info=True)
        return

    logger.info("[%s] Processing %d products", retailer.name, len(products))
    alerts_sent = 0
    for product in products:
        try:
            prev, is_new = await db.upsert_product(product)
            sent = await alerter.process_product(product, prev, is_new)
            if sent:
                alerts_sent += 1
        except Exception as e:
            logger.error("[%s] Error processing product %s: %s", retailer.name, product.name[:40], e)

    logger.info("[%s] Done — %d products, %d alerts sent", retailer.name, len(products), alerts_sent)


async def run_all_retailers(
    db: Database,
    alerter: Alerter,
    config: AppConfig,
    http: HttpClient,
    browser: BrowserClient | None,
) -> None:
    """Run all enabled retailers concurrently (with per-retailer jitter)."""

    async def _run_with_jitter(retailer: BaseRetailer) -> None:
        jitter = random.uniform(0, config.poll_jitter_seconds)
        if jitter > 0:
            logger.debug("[%s] Jitter: sleeping %.1fs", retailer.name, jitter)
            await asyncio.sleep(jitter)
        await run_single_retailer(retailer, db, alerter, config)

    retailers: list[BaseRetailer] = []
    for key, cls in RETAILER_MAP.items():
        cfg = config.retailers.get(key)
        if cfg and cfg.enabled:
            try:
                r = cls(config, http, browser)
                retailers.append(r)
            except Exception as e:
                logger.error("Failed to initialize retailer %s: %s", key, e)

    if not retailers:
        logger.warning("No retailers enabled")
        return

    tasks = [_run_with_jitter(r) for r in retailers]
    await asyncio.gather(*tasks, return_exceptions=True)


class Scheduler:
    """
    Long-running asyncio scheduler.
    Runs all retailers every `interval_seconds` ± jitter.
    Optionally posts a daily digest.
    """

    def __init__(
        self,
        db: Database,
        alerter: Alerter,
        config: AppConfig,
        http: HttpClient,
        browser: BrowserClient | None = None,
    ) -> None:
        self._db = db
        self._alerter = alerter
        self._config = config
        self._http = http
        self._browser = browser
        self._stop_event = asyncio.Event()
        self._last_digest_day: int | None = None

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        logger.info(
            "Scheduler started — interval: %ds ± %ds",
            self._config.poll_interval_seconds,
            self._config.poll_jitter_seconds,
        )
        while not self._stop_event.is_set():
            start = asyncio.get_event_loop().time()

            # Check if daily digest should be sent
            if self._config.discord_daily_digest:
                await self._maybe_send_digest()

            # Run all retailers
            await run_all_retailers(
                self._db,
                self._alerter,
                self._config,
                self._http,
                self._browser,
            )

            elapsed = asyncio.get_event_loop().time() - start
            sleep_time = max(
                0,
                self._config.poll_interval_seconds - elapsed
            )
            logger.info("Cycle done in %.1fs — sleeping %.1fs", elapsed, sleep_time)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_time)
            except asyncio.TimeoutError:
                pass  # Normal — just means sleep is done

        logger.info("Scheduler stopped")

    async def _maybe_send_digest(self) -> None:
        now = datetime.utcnow()
        today = now.date().toordinal()
        if self._last_digest_day == today:
            return

        # Check if it's time to send the digest
        try:
            h, m = self._config.discord_digest_time.split(":")
            target = dtime(int(h), int(m))
        except (ValueError, AttributeError):
            return

        current_time = now.time()
        # Send if we're within 15 minutes of the digest time and haven't sent today
        diff_minutes = abs(
            (current_time.hour * 60 + current_time.minute)
            - (target.hour * 60 + target.minute)
        )
        if diff_minutes <= 15:
            self._last_digest_day = today
            try:
                await self._alerter.send_daily_digest()
            except Exception as e:
                logger.error("Daily digest failed: %s", e)
