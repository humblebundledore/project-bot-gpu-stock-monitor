"""Rue du Commerce retailer adapter — rueducommerce.fr"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup, Tag

from ..models import GPUTarget, Product
from .base import BaseRetailer

logger = logging.getLogger(__name__)


class RueDuCommerceRetailer(BaseRetailer):
    """
    Adapter for Rue du Commerce (rueducommerce.fr).

    RDC is a marketplace/retailer hybrid — Rue du Commerce sells directly,
    but also has third-party marketplace sellers. We capture seller info.
    JS rendering is used for listing pages, so Playwright is enabled.
    """

    @staticmethod
    def retailer_key() -> str:
        return "rueducommerce"

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

        # HTML card selectors for Rue du Commerce
        items = soup.select(
            "div[class*='product-item'], article[class*='product'], "
            "li[class*='product'], div[class*='card-product'], "
            "[data-product-id], [data-sku]"
        )
        if not items:
            logger.warning("[RueDuCommerce] No product items found on %s", page_url)
            return []

        for item in items:
            try:
                p = self._parse_item(item, page_url, targets)
                if p:
                    products.append(p)
            except Exception as e:
                logger.debug("[RueDuCommerce] Error parsing item: %s", e)

        return products

    def _parse_item(self, item: Tag, page_url: str, targets: list[GPUTarget]) -> Product | None:
        # Name
        name_tag = item.select_one(
            "h2 a, h3 a, a[class*='title'], a[class*='name'], "
            "[class*='product-title'] a, [class*='product-name'] a"
        )
        if not name_tag:
            name_tag = item.select_one("a[href*='/carte-graphique']")
        if not name_tag:
            name_tag = item.select_one("a[title]")
        if not name_tag:
            return None

        name = name_tag.get("title") or name_tag.get_text(strip=True)
        if not name:
            return None
        href = name_tag.get("href", "")
        url = self._abs_url(self._retailer_cfg.base_url, str(href))

        # Price — RDC often has data-price attributes
        price_text = ""
        price_tag = item.select_one(
            "[class*='price']:not([class*='old']):not([class*='crossed']), "
            "[data-price], [itemprop='price'], [class*='prix']"
        )
        if price_tag:
            price_text = (
                price_tag.get("content")
                or price_tag.get("data-price")
                or price_tag.get_text(strip=True)
            )

        # Stock
        stock_tag = item.select_one(
            "[class*='stock'], [class*='dispo'], [class*='availability'], "
            "[class*='livraison'], [class*='delivery']"
        )
        status_text = stock_tag.get_text(separator=" ", strip=True) if stock_tag else ""

        # Seller — RDC marketplace
        seller_tag = item.select_one(
            "[class*='seller'], [class*='merchant'], [class*='vendeur']"
        )
        seller = seller_tag.get_text(strip=True) if seller_tag else "Rue du Commerce"
        # Normalize seller name
        if not seller or len(seller) < 2:
            seller = "Rue du Commerce"

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
            # Pick the cheapest available offer
            available = [
                o for o in offers
                if "InStock" in str(o.get("availability", ""))
                or "PreOrder" in str(o.get("availability", ""))
            ]
            offers = available[0] if available else (offers[0] if offers else {})

        price_str = str(offers.get("price", ""))
        avail = offers.get("availability", "")
        avail_map = {
            "InStock": "En stock",
            "OutOfStock": "Rupture de stock",
            "PreOrder": "Pré-commande",
            "BackOrder": "Sur commande",
        }
        status_text = avail_map.get(avail.split("/")[-1], avail)
        seller = offers.get("seller", {}).get("name") if isinstance(offers.get("seller"), dict) else None
        return self._make_product(name, url, status_text, price_str, targets, seller=seller)
