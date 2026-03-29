"""LDLC retailer adapter — ldlc.com"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from ..models import GPUTarget, Product
from .base import BaseRetailer

logger = logging.getLogger(__name__)


class LDLCRetailer(BaseRetailer):
    """
    Adapter for LDLC (ldlc.com).

    LDLC renders search results as static HTML, so no Playwright needed.
    Product cards are in <li class="pdt-item"> elements.
    Stock status is indicated by <div class="dispo"> or similar class.
    """

    @staticmethod
    def retailer_key() -> str:
        return "ldlc"

    def parse_products(
        self,
        html: str,
        page_url: str,
        targets: list[GPUTarget],
    ) -> list[Product]:
        soup = BeautifulSoup(html, "lxml")
        products: list[Product] = []

        # LDLC search result items — class varies: "pdt-item", "article"
        items = soup.select("li.pdt-item, article.pdt-item, div.pdt-item")
        if not items:
            # Try JSON-LD structured data first
            products = self._parse_json_ld(soup, page_url, targets)
            if products:
                return products
            logger.warning("[LDLC] No product items found on %s", page_url)
            return []

        for item in items:
            try:
                product = self._parse_item(item, page_url, targets)
                if product:
                    products.append(product)
            except Exception as e:
                logger.debug("[LDLC] Error parsing item: %s", e)

        return products

    def _parse_item(self, item: Tag, page_url: str, targets: list[GPUTarget]) -> Product | None:
        # Product name
        name_tag = item.select_one("h3.designation a, .pdt-desc a, h2.title a")
        if not name_tag:
            return None
        name = name_tag.get_text(strip=True)

        # URL
        href = name_tag.get("href", "")
        url = self._abs_url(self._retailer_cfg.base_url, str(href))

        # Price — look for <div class="price"> or <span class="prix">
        price_tag = item.select_one(".price, .prix, [class*='price']")
        price_text = price_tag.get_text(strip=True) if price_tag else ""

        # Stock / availability
        stock_tag = item.select_one(".dispo, .stock, [class*='dispo'], [class*='stock']")
        if stock_tag:
            status_text = stock_tag.get_text(separator=" ", strip=True)
        else:
            # Look for button text as fallback
            btn = item.select_one("button, .btn-add-to-cart, [class*='add-cart']")
            status_text = btn.get_text(strip=True) if btn else ""

        return self._make_product(name, url, status_text, price_text, targets)

    def _parse_json_ld(
        self, soup: BeautifulSoup, page_url: str, targets: list[GPUTarget]
    ) -> list[Product]:
        """Try to extract products from JSON-LD schema.org data."""
        import json
        products = []
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                # Could be a single item or a list
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") not in ("Product", "ItemList"):
                        continue
                    if item.get("@type") == "ItemList":
                        for elem in item.get("itemListElement", []):
                            p = self._from_schema_product(
                                elem.get("item", elem), page_url, targets
                            )
                            if p:
                                products.append(p)
                    else:
                        p = self._from_schema_product(item, page_url, targets)
                        if p:
                            products.append(p)
            except (json.JSONDecodeError, AttributeError):
                continue
        return products

    def _from_schema_product(self, item: dict, page_url: str, targets: list[GPUTarget]) -> Product | None:
        name = item.get("name", "")
        if not name:
            return None
        url = item.get("url", page_url)
        offers = item.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_str = str(offers.get("price", ""))
        availability = offers.get("availability", "")
        # Map schema.org availability to human-readable
        avail_map = {
            "http://schema.org/InStock": "En stock",
            "https://schema.org/InStock": "En stock",
            "http://schema.org/OutOfStock": "Rupture de stock",
            "https://schema.org/OutOfStock": "Rupture de stock",
            "http://schema.org/PreOrder": "Pré-commande",
            "https://schema.org/PreOrder": "Pré-commande",
            "http://schema.org/BackOrder": "Sur commande",
            "https://schema.org/BackOrder": "Sur commande",
        }
        status_text = avail_map.get(availability, availability)
        return self._make_product(name, url, status_text, price_str, targets)
