"""Alternate.fr retailer adapter — alternate.fr (ships to France)"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup, Tag

from ..models import GPUTarget, Product
from .base import BaseRetailer

logger = logging.getLogger(__name__)


class AlternateRetailer(BaseRetailer):
    """
    Adapter for Alternate.fr (German retailer that ships to France).

    Alternate uses heavy JS rendering, so this adapter is backed by Playwright.
    Product listing cards use data attributes and class names common to Alternate's
    frontend framework.
    """

    @staticmethod
    def retailer_key() -> str:
        return "alternate"

    def parse_products(
        self,
        html: str,
        page_url: str,
        targets: list[GPUTarget],
    ) -> list[Product]:
        soup = BeautifulSoup(html, "lxml")

        # Try JSON-LD first (Alternate sometimes embeds structured data)
        products = self._parse_json_ld(soup, page_url, targets)
        if products:
            return products

        # Look for product listing cards
        # Alternate typically uses <article class="productBox"> or similar
        items = soup.select(
            "article[class*='productBox'], article[class*='product-box'], "
            "div[class*='productBox'], li[class*='productListItem'], "
            "div[data-testid*='product'], article.product"
        )

        if not items:
            # Try more generic fallback
            items = soup.select("article, div[class*='product']")
            # Filter to only those with a price
            items = [
                i for i in items
                if i.select_one("[class*='price']") and i.select_one("a[href]")
            ]

        if not items:
            logger.warning("[Alternate] No product items found on %s", page_url)
            return []

        for item in items:
            try:
                p = self._parse_item(item, page_url, targets)
                if p:
                    products.append(p)
            except Exception as e:
                logger.debug("[Alternate] Error parsing item: %s", e)

        return products

    def _parse_item(self, item: Tag, page_url: str, targets: list[GPUTarget]) -> Product | None:
        # Name
        name_tag = item.select_one(
            "h2 a, h3 a, a[class*='productTitle'], a[class*='product-title'], "
            "[class*='name'] a, [class*='title'] a"
        )
        if not name_tag:
            # Try any primary link
            name_tag = item.select_one("a[href*='/html/']")
        if not name_tag:
            return None
        name = name_tag.get_text(strip=True)
        if not name:
            # Some links wrap an <img> — use alt or title
            img = name_tag.select_one("img")
            if img:
                name = img.get("alt") or img.get("title") or ""
        if not name:
            return None

        href = name_tag.get("href", "")
        url = self._abs_url(self._retailer_cfg.base_url, str(href))

        # Price
        price_tag = item.select_one(
            "[class*='price']:not([class*='old']):not([class*='crossed']):not([class*='rrp']), "
            "[data-price], [itemprop='price']"
        )
        price_text = ""
        if price_tag:
            price_text = (
                price_tag.get("content")
                or price_tag.get("data-price")
                or price_tag.get_text(strip=True)
            )

        # Stock — Alternate uses "lieferbar", "nicht lieferbar" etc.
        # Also look for French text if locale is fr
        stock_tag = item.select_one(
            "[class*='stock'], [class*='availability'], [class*='lieferstatus'], "
            "[class*='dispo'], [class*='delivery']"
        )
        status_text = stock_tag.get_text(separator=" ", strip=True) if stock_tag else ""

        # Also check data attributes for stock
        if not status_text:
            for attr in ("data-availability", "data-stock", "data-lieferstatus"):
                val = item.get(attr)
                if val:
                    status_text = str(val)
                    break

        # Map German status to French if needed
        status_text = self._translate_status(status_text)

        return self._make_product(name, url, status_text, price_text, targets)

    @staticmethod
    def _translate_status(text: str) -> str:
        """Translate common German availability strings to French-compatible ones."""
        mapping = {
            "lieferbar": "En stock",
            "sofort lieferbar": "En stock",
            "nicht lieferbar": "Rupture de stock",
            "auf lager": "En stock",
            "nicht auf lager": "Rupture de stock",
            "vorbestellbar": "Pré-commande",
            "auf anfrage": "Sur commande",
        }
        lower = text.lower().strip()
        return mapping.get(lower, text)

    def _parse_json_ld(
        self, soup: BeautifulSoup, page_url: str, targets: list[GPUTarget]
    ) -> list[Product]:
        products = []
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    t = item.get("@type", "")
                    if t == "ItemList":
                        for elem in item.get("itemListElement", []):
                            p = self._from_schema(elem.get("item", elem), page_url, targets)
                            if p:
                                products.append(p)
                    elif t == "Product":
                        p = self._from_schema(item, page_url, targets)
                        if p:
                            products.append(p)
            except (json.JSONDecodeError, AttributeError):
                continue
        return products

    def _from_schema(self, item: dict, page_url: str, targets: list[GPUTarget]) -> Product | None:
        name = item.get("name", "")
        if not name:
            return None
        url = item.get("url", page_url)
        offers = item.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_str = str(offers.get("price", ""))
        avail = offers.get("availability", "")
        avail_map = {
            "InStock": "En stock",
            "OutOfStock": "Rupture de stock",
            "PreOrder": "Pré-commande",
            "BackOrder": "Sur commande",
        }
        status_text = avail_map.get(avail.split("/")[-1], avail)
        return self._make_product(name, url, status_text, price_str, targets)
