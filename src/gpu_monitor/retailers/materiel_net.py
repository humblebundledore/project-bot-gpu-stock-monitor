"""Materiel.net retailer adapter — materiel.net"""

from __future__ import annotations

import json
import logging

from bs4 import BeautifulSoup, Tag

from ..models import GPUTarget, Product
from .base import BaseRetailer

logger = logging.getLogger(__name__)


class MaterielNetRetailer(BaseRetailer):
    """
    Adapter for Materiel.net.

    Materiel.net is a French retailer with static search results.
    Product cards are in article or li elements with class patterns.
    """

    @staticmethod
    def retailer_key() -> str:
        return "materiel_net"

    def parse_products(
        self,
        html: str,
        page_url: str,
        targets: list[GPUTarget],
    ) -> list[Product]:
        soup = BeautifulSoup(html, "lxml")

        # JSON-LD first
        products = self._parse_json_ld(soup, page_url, targets)
        if products:
            return products

        # HTML cards
        items = soup.select(
            "article.c-product-card, li[class*='product'], div[class*='product-item'],"
            " div.product, li.product"
        )
        if not items:
            logger.warning("[Materiel.net] No product items found on %s", page_url)
            return []

        for item in items:
            try:
                p = self._parse_item(item, page_url, targets)
                if p:
                    products.append(p)
            except Exception as e:
                logger.debug("[Materiel.net] Error parsing item: %s", e)

        return products

    def _parse_item(self, item: Tag, page_url: str, targets: list[GPUTarget]) -> Product | None:
        # Name — Materiel.net typically uses h3 or h2 with a link
        name_tag = item.select_one(
            "h3 a, h2 a, .c-product-card__title a, a[class*='title'], a[class*='name']"
        )
        if not name_tag:
            return None
        name = name_tag.get_text(strip=True)
        href = name_tag.get("href", "")
        url = self._abs_url(self._retailer_cfg.base_url, str(href))

        # Price
        price_tag = item.select_one(
            "[class*='price']:not([class*='old']):not([class*='crossed']), "
            "[itemprop='price'], .c-product-price"
        )
        price_text = ""
        if price_tag:
            price_text = (
                price_tag.get("content")
                or price_tag.get("data-price")
                or price_tag.get_text(strip=True)
            )

        # Stock
        stock_tag = item.select_one(
            "[class*='stock'], [class*='dispo'], [class*='availability'], "
            ".c-product-card__availability"
        )
        status_text = stock_tag.get_text(separator=" ", strip=True) if stock_tag else ""

        # Seller (marketplace)
        seller_tag = item.select_one("[class*='seller'], [class*='merchant']")
        seller = seller_tag.get_text(strip=True) if seller_tag else None

        return self._make_product(name, url, status_text, price_text, targets, seller=seller)

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
