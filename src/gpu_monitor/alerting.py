"""
Alerting logic: decide when to alert, format messages, post to Discord.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .config import AppConfig
from .db import Database
from .discord_client import DiscordClient
from .models import (
    ALERTABLE_STATUSES,
    INACTIVE_STATUSES,
    Product,
    StockStatus,
    StoredProduct,
)

logger = logging.getLogger(__name__)

# Discord embed colours
COLOR_IN_STOCK = 0x57F287   # green
COLOR_PREORDER = 0x5865F2   # blue
COLOR_BACKORDER = 0xFEE75C  # yellow-orange
COLOR_DEFAULT   = 0x99AAB5  # grey

STATUS_EMOJI = {
    StockStatus.IN_STOCK:  "✅",
    StockStatus.PREORDER:  "🟦",
    StockStatus.BACKORDER: "🟧",
    StockStatus.OUT_OF_STOCK: "❌",
    StockStatus.UNKNOWN:   "❓",
}

STATUS_COLOR = {
    StockStatus.IN_STOCK:  COLOR_IN_STOCK,
    StockStatus.PREORDER:  COLOR_PREORDER,
    StockStatus.BACKORDER: COLOR_BACKORDER,
}


def _format_price(price: float | None) -> str:
    if price is None:
        return "Prix inconnu"
    return f"{price:,.2f} €".replace(",", "\u00a0").replace(".", ",")


def _is_below_ceiling(product: Product, config: AppConfig) -> bool:
    target = config.gpu_target_by_family(product.gpu_family)
    if not target or product.price_eur is None:
        return True  # No ceiling info → allow
    return product.price_eur <= target.price_ceiling_eur


def _price_ceiling(product: Product, config: AppConfig) -> float | None:
    target = config.gpu_target_by_family(product.gpu_family)
    return target.price_ceiling_eur if target else None


def should_alert(
    product: Product,
    prev: StoredProduct | None,
    is_new: bool,
    config: AppConfig,
) -> tuple[bool, str]:
    """
    Decide if an alert should be sent.
    Returns (should_alert, reason_string).
    """
    # Must be an alertable status
    if product.status not in ALERTABLE_STATUSES:
        return False, "status not alertable"

    # Must be within price ceiling
    if not _is_below_ceiling(product, config):
        ceiling = _price_ceiling(product, config)
        return False, f"price {product.price_eur} > ceiling {ceiling}"

    if is_new:
        return True, "new product found"

    if prev is None:
        return True, "no previous record"

    # Status transition from inactive → active
    if prev.status in INACTIVE_STATUSES and product.status in ALERTABLE_STATUSES:
        return True, f"status {prev.status} → {product.status}"

    # Price drop to below ceiling (was above or unknown, now below)
    prev_price = prev.price_eur
    curr_price = product.price_eur
    ceiling = _price_ceiling(product, config)
    if (
        ceiling is not None
        and curr_price is not None
        and prev_price is not None
        and prev_price > ceiling
        and curr_price <= ceiling
    ):
        return True, f"price dropped {prev_price:.0f}→{curr_price:.0f} (ceiling {ceiling:.0f})"

    return False, "no change warranting alert"


def format_alert_message(product: Product, reason: str, config: AppConfig) -> str:
    """
    Format a plain-text Discord message (fallback when embeds not used).
    """
    emoji = STATUS_EMOJI.get(product.status, "❓")
    price_str = _format_price(product.price_eur)
    ceiling = _price_ceiling(product, config)
    ceiling_str = f" (plafond: {_format_price(ceiling)})" if ceiling else ""
    ts = product.scraped_at.strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"{emoji} **{product.name}**",
        f"🏪 Retailer: **{product.retailer}**",
        f"💰 Prix: **{price_str}**{ceiling_str}",
        f"📦 Statut: **{product.status.value}**",
    ]
    if product.availability_text:
        lines.append(f"📋 Dispo: {product.availability_text}")
    if product.brand:
        lines.append(f"🏷️ Marque: {product.brand}")
    if product.seller and product.seller != product.retailer:
        lines.append(f"👤 Vendeur: {product.seller}")
    lines.append(f"🔗 {product.url}")
    lines.append(f"🕐 {ts} • id:`{product.product_id}` • {reason}")
    return "\n".join(lines)


class Alerter:
    def __init__(self, db: Database, discord: DiscordClient, config: AppConfig) -> None:
        self._db = db
        self._discord = discord
        self._config = config

    async def process_product(
        self, product: Product, prev: StoredProduct | None, is_new: bool
    ) -> bool:
        """
        Evaluate alert conditions and send alert if needed.
        Returns True if an alert was sent.
        """
        do_alert, reason = should_alert(product, prev, is_new, self._config)
        if not do_alert:
            logger.debug("No alert for %s: %s", product.name[:40], reason)
            return False

        # Check cooldown
        in_cooldown = await self._db.recent_alert_exists(
            product.alert_key, self._config.cooldown_seconds
        )
        if in_cooldown:
            logger.debug("Alert suppressed (cooldown) for %s", product.name[:40])
            return False

        await self._send_alert(product, reason)
        await self._db.mark_alerted(product, reason)
        return True

    async def _send_alert(self, product: Product, reason: str) -> None:
        try:
            await self._discord.send_embed(
                title=f"{STATUS_EMOJI.get(product.status, '❓')} {product.name}",
                description=self._build_embed_description(product, reason),
                color=STATUS_COLOR.get(product.status, COLOR_DEFAULT),
                url=product.url,
                fields=self._build_embed_fields(product),
                footer=f"id:{product.product_id} • {reason}",
            )
        except Exception as e:
            logger.warning("Embed failed (%s), falling back to plain text", e)
            try:
                msg = format_alert_message(product, reason, self._config)
                await self._discord.send_message(msg)
            except Exception as e2:
                logger.error("Discord alert failed entirely: %s", e2)

    def _build_embed_description(self, product: Product, reason: str) -> str:
        price_str = _format_price(product.price_eur)
        ceiling = _price_ceiling(product, self._config)
        desc = f"**{product.retailer}** — {price_str}"
        if ceiling:
            desc += f" *(plafond: {_format_price(ceiling)})*"
        if product.availability_text:
            desc += f"\n{product.availability_text}"
        return desc

    def _build_embed_fields(self, product: Product) -> list[dict]:
        fields = [
            {"name": "Statut", "value": product.status.value, "inline": True},
            {"name": "Retailer", "value": product.retailer, "inline": True},
        ]
        if product.brand:
            fields.append({"name": "Marque", "value": product.brand, "inline": True})
        if product.seller and product.seller != product.retailer:
            fields.append({"name": "Vendeur", "value": product.seller, "inline": True})
        ts = product.scraped_at.strftime("%Y-%m-%d %H:%M UTC")
        fields.append({"name": "Détecté", "value": ts, "inline": False})
        return fields

    async def send_test_alert(self) -> None:
        """Send a test alert to validate the Discord integration."""
        from datetime import datetime as dt
        test_product = Product(
            retailer="Test Retailer",
            name="ASUS TUF Gaming GeForce RTX 5080 16GB OC",
            url="https://example.com/test",
            gpu_family="RTX_5080",
            status=StockStatus.IN_STOCK,
            price_eur=1299.99,
            availability_text="En stock — Livraison immédiate",
            brand="ASUS",
            seller=None,
            scraped_at=dt.utcnow(),
        )
        logger.info("Sending test alert…")
        await self._send_alert(test_product, "test alert")
        logger.info("Test alert sent.")

    async def send_daily_digest(self) -> None:
        """Post a daily summary of tracked products."""
        products = await self._db.list_products()
        if not products:
            await self._discord.send_message(
                "📊 **GPU Monitor — Résumé quotidien**\n_Aucun produit suivi pour l'instant._"
            )
            return

        lines = ["📊 **GPU Monitor — Résumé quotidien**\n"]
        by_family: dict[str, list] = {}
        for p in products:
            by_family.setdefault(p.gpu_family, []).append(p)

        for family, items in sorted(by_family.items()):
            lines.append(f"**{family}** ({len(items)} produits)")
            in_stock = [i for i in items if i.status == StockStatus.IN_STOCK]
            preorder = [i for i in items if i.status == StockStatus.PREORDER]
            backorder = [i for i in items if i.status == StockStatus.BACKORDER]
            out = [i for i in items if i.status == StockStatus.OUT_OF_STOCK]

            if in_stock:
                lines.append(f"  ✅ En stock: {len(in_stock)}")
                for p in in_stock[:3]:
                    lines.append(f"    • {p.name[:50]} — {_format_price(p.price_eur)} @ {p.retailer}")
            if preorder:
                lines.append(f"  🟦 Précommande: {len(preorder)}")
            if backorder:
                lines.append(f"  🟧 Sur commande: {len(backorder)}")
            if out:
                lines.append(f"  ❌ Rupture: {len(out)}")
            lines.append("")

        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"_Mis à jour: {ts}_")

        await self._discord.send_message("\n".join(lines))
