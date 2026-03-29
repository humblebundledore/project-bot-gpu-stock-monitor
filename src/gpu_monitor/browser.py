"""Playwright-based browser fallback for JS-heavy retailer pages."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_playwright_available = False
try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    _playwright_available = True
except ImportError:
    logger.warning("Playwright not installed — browser fallback disabled")


class BrowserClient:
    """
    Manages a shared Playwright browser instance.
    Call start() before use, stop() when done.
    """

    def __init__(
        self,
        headless: bool = True,
        screenshot_dir: str = "logs/screenshots",
        user_agents: list[str] | None = None,
    ) -> None:
        self._headless = headless
        self._screenshot_dir = Path(screenshot_dir)
        self._user_agents = user_agents or [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ]
        self._playwright = None
        self._browser: Optional["Browser"] = None

    async def start(self) -> None:
        if not _playwright_available:
            raise RuntimeError("Playwright is not installed. Run: playwright install chromium")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        logger.debug("Playwright browser started")

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.debug("Playwright browser stopped")

    async def __aenter__(self) -> "BrowserClient":
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.stop()

    async def fetch_html(
        self,
        url: str,
        *,
        wait_for_selector: str | None = None,
        wait_ms: int = 2000,
        retailer_name: str = "unknown",
    ) -> str:
        """
        Navigate to URL and return full page HTML.
        Optionally wait for a CSS selector to appear.
        On error, saves a screenshot for debugging.
        """
        if self._browser is None:
            raise RuntimeError("BrowserClient not started")

        ua = random.choice(self._user_agents)
        context: BrowserContext = await self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
            extra_http_headers={
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
        )

        # Stealth: hide webdriver property
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page: Page = await context.new_page()
        try:
            # Polite delay
            await asyncio.sleep(random.uniform(1.0, 3.0))

            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=10_000)
                except Exception:
                    logger.debug("Selector %r not found on %s — continuing anyway", wait_for_selector, url)

            # Extra wait for any lazy JS rendering
            await page.wait_for_timeout(wait_ms)

            html = await page.content()
            return html

        except Exception as e:
            logger.error("Browser fetch failed for %s: %s", url, e)
            await self._save_screenshot(page, retailer_name, url)
            raise

        finally:
            await page.close()
            await context.close()

    async def _save_screenshot(self, page: "Page", retailer: str, url: str) -> None:
        try:
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)
            safe_url = url.replace("/", "_").replace(":", "")[:60]
            path = self._screenshot_dir / f"{retailer}_{safe_url}.png"
            await page.screenshot(path=str(path), full_page=True)
            logger.info("Screenshot saved: %s", path)
        except Exception as e:
            logger.debug("Failed to save screenshot: %s", e)
