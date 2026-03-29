"""Base retailer adapter interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from bs4 import BeautifulSoup

from ..browser import BrowserClient
from ..config import AppConfig
from ..http_client import HttpClient
from ..models import GPUTarget, Product, RetailerConfig
from ..normalizer import detect_brand, match_gpu_family, normalize_status, parse_price, should_exclude

logger = logging.getLogger(__name__)


class BaseRetailer(ABC):
    """
    Abstract base for all retailer adapters.

    Subclasses must implement:
        parse_products(html, url, targets) -> list[Product]

    Optionally override:
        fetch(url) -> str       if the default HTTP/browser logic is insufficient
    """

    def __init__(
        self,
        config: AppConfig,
        http_client: HttpClient,
        browser: BrowserClient | None = None,
    ) -> None:
        self._config = config
        self._http = http_client
        self._browser = browser
        self._retailer_cfg: RetailerConfig = self._get_retailer_config()

    @property
    def name(self) -> str:
        return self._retailer_cfg.name

    @property
    def key(self) -> str:
        return self._retailer_cfg.key

    @property
    def use_browser(self) -> bool:
        return self._retailer_cfg.use_browser

    def _get_retailer_config(self) -> RetailerConfig:
        key = self.retailer_key()
        cfg = self._config.retailers.get(key)
        if cfg is None:
            raise ValueError(f"Retailer '{key}' not found in config")
        return cfg

    @staticmethod
    @abstractmethod
    def retailer_key() -> str:
        """Return the config key for this retailer (e.g. 'ldlc')."""

    @abstractmethod
    def parse_products(
        self,
        html: str,
        page_url: str,
        targets: list[GPUTarget],
    ) -> list[Product]:
        """Parse HTML and return a list of Product objects."""

    async def fetch(self, url: str) -> str:
        """Fetch page HTML, using browser if configured."""
        if self.use_browser:
            if self._browser is None:
                raise RuntimeError(
                    f"Retailer {self.name} requires Playwright but no browser was provided"
                )
            return await self._browser.fetch_html(
                url,
                retailer_name=self.key,
                wait_ms=2500,
            )
        return (await self._http.get(url)).text

    async def scrape(self) -> list[Product]:
        """
        Fetch all configured search URLs and return all matched products.
        This is the main entry point called by the scheduler.
        """
        targets = self._config.gpu_targets
        all_products: list[Product] = []
        seen_urls: set[str] = set()

        for url in self._retailer_cfg.search_urls:
            try:
                logger.debug("[%s] Fetching %s", self.name, url)
                html = await self.fetch(url)
                products = self.parse_products(html, url, targets)
                for p in products:
                    if p.url not in seen_urls:
                        seen_urls.add(p.url)
                        all_products.append(p)
                logger.info("[%s] Found %d products at %s", self.name, len(products), url)
            except Exception as e:
                logger.error("[%s] Error scraping %s: %s", self.name, url, e, exc_info=True)

        return all_products

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------

    def _make_product(
        self,
        name: str,
        url: str,
        status_text: str,
        price_text: str,
        targets: list[GPUTarget],
        seller: str | None = None,
    ) -> Product | None:
        """
        Build a Product from raw strings.
        Returns None if the product doesn't match any GPU target or is excluded.
        """
        if should_exclude(name):
            logger.debug("[%s] Excluded: %s", self.name, name[:60])
            return None

        target = match_gpu_family(name, targets)
        if target is None:
            return None

        status = normalize_status(status_text)
        price = parse_price(price_text)
        brand = detect_brand(name)

        return Product(
            retailer=self.name,
            name=name.strip(),
            url=url,
            gpu_family=target.family,
            status=status,
            price_eur=price,
            availability_text=status_text.strip(),
            brand=brand,
            seller=seller,
        )

    @staticmethod
    def _abs_url(base: str, href: str) -> str:
        """Make an absolute URL from a possibly relative href."""
        if href.startswith("http"):
            return href
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base)
            return f"{parsed.scheme}://{parsed.netloc}{href}"
        return base.rstrip("/") + "/" + href
