"""TopAchat retailer adapter — topachat.com"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup, Tag

from ..models import GPUTarget, Product
from .base import BaseRetailer

logger = logging.getLogger(__name__)


class TopAchatRetailer(BaseRetailer):
    """
    Adapter for TopAchat (topachat.com).

    TopAchat uses a fairly static HTML structure.
    Product listings are within article.product or similar containers.
    """

    @staticmethod
    def retailer_key() -> str:
        return "topachat"

    def parse_products(
        self,
        html: str,
        page_url: str,
        targets: list[GPUTarget],
    ) -> list[Product]:
        soup = BeautifulSoup(html, "lxml")

        # Try JSON-LD first
        products = self._parse_json_ld(soup, page_url, targets)
        if products:
            return products

        # Fallback: HTML cards
        items = soup.select("article.product, li.product, div[class*='product-item']")
        if not items:
            logger.warning("[TopAchat] No product items found on %s", page_url)
            return []

        for item in items:
            try:
                p = self._parse_item(item, page_url, targets)
                if p:
                    products.append(p)
            except Exception as e:
                logger.debug("[TopAchat] Error parsing item: %s", e)

        return products

    def _parse_item(self, item: Tag, page_url: str, targets: list[GPUTarget]) -> Product | None:
        # Name
        name_tag = item.select_one("h2 a, h3 a, .product-name a, a.title")
        if not name_tag:
            return None
        name = name_tag.get_text(strip=True)
        href = name_tag.get("href", "")
        url = self._abs_url(self._retailer_cfg.base_url, str(href))

        # Price
        price_tag = item.select_one(".price, .prix, [class*='price'], [itemprop='price']")
        price_text = ""
        if price_tag:
            price_text = price_tag.get("content") or price_tag.get_text(strip=True)

        # Stock
        stock_tag = item.select_one(
            ".stock, .dispo, [class*='stock'], [class*='dispo'], [class*='availability']"
        )
        status_text = stock_tag.get_text(separator=" ", strip=True) if stock_tag else ""

        # Fallback: check add-to-cart button
        if not status_text:
            btn = item.select_one("button[class*='cart'], a[class*='cart'], [class*='add-to']")
            status_text = btn.get_text(strip=True) if btn else ""

        return self._make_product(name, url, status_text, price_text, targets)

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
        currency = offers.get("priceCurrency", "EUR")
        price_text = f"{price_str} {"€" if currency == "EUR" else currency}" if price_str else ""
        avail = offers.get("availability", "")
        avail_map = {
            "InStock": "En stock",
            "OutOfStock": "Rupture de stock",
            "PreOrder": "Pré-commande",
            "BackOrder": "Sur commande",
        }
        status_text = avail_map.get(avail.split("/")[-1], avail)
        return self._make_product(name, url, status_text, price_text, targets)
