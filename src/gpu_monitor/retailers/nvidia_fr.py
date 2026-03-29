"""NVIDIA France official store — Founders Edition cards."""

from __future__ import annotations

import json
import logging

from ..models import GPUTarget, Product
from .base import BaseRetailer

logger = logging.getLogger(__name__)


class NvidiaFrRetailer(BaseRetailer):
    """
    Adapter for the NVIDIA France store (store.nvidia.com/fr-fr).

    Queries the NVIDIA partner FE inventory API which returns JSON for all
    Founders Edition cards in a given locale. Only FE cards are sold here.
    """

    @staticmethod
    def retailer_key() -> str:
        return "nvidia_fr"

    async def fetch(self, url: str) -> str:
        # NVIDIA's inventory API rejects HTTP/2 with StreamReset (error_code=2);
        # force HTTP/1.1 for this retailer.
        resp = await self._http.get(
            url,
            extra_headers={"Accept": "application/json"},
            politeness_delay=0.5,
            http2=False,
        )
        return resp.text

    def parse_products(
        self,
        html: str,
        page_url: str,
        targets: list[GPUTarget],
    ) -> list[Product]:
        """Parse NVIDIA FE inventory API JSON response."""
        try:
            data = json.loads(html)
        except json.JSONDecodeError as exc:
            logger.error("[nvidia_fr] JSON parse error: %s", exc)
            return []

        if not data.get("success"):
            logger.warning("[nvidia_fr] API returned success=false")
            return []

        products: list[Product] = []
        seen_urls: set[str] = set()

        for item in data.get("listMap", []):
            title: str = item.get("product_title", "").strip()
            if not title:
                continue

            is_active = str(item.get("is_active", "false")).lower() == "true"
            status_text = "En stock" if is_active else "Indisponible"

            # Prefer a direct purchase link, fall back to store page
            product_url = ""
            for r in item.get("retailers", []):
                link = r.get("purchaseLink", "")
                if link:
                    product_url = link
                    break
            if not product_url:
                product_url = self._retailer_cfg.base_url + "/geforce/store/gpu/"

            price_raw = item.get("price", "")
            price_text = f"{price_raw} \u20ac" if price_raw else ""

            product = self._make_product(
                name=title,
                url=product_url,
                status_text=status_text,
                price_text=price_text,
                targets=targets,
            )
            if product and product_url not in seen_urls:
                seen_urls.add(product_url)
                products.append(product)

        return products
