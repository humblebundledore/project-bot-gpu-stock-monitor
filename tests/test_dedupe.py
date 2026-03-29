"""Tests for deduplication and alert decision logic."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from gpu_monitor.alerting import should_alert
from gpu_monitor.models import Product, StockStatus, StoredProduct


def make_product(
    status: StockStatus = StockStatus.IN_STOCK,
    price: float = 1200.0,
    family: str = "RTX_5080",
) -> Product:
    return Product(
        retailer="LDLC",
        name="ASUS TUF Gaming RTX 5080 OC",
        url="https://ldlc.com/fiche/PB0001.html",
        gpu_family=family,
        status=status,
        price_eur=price,
        availability_text="En stock",
        brand="ASUS",
        seller=None,
        scraped_at=datetime.utcnow(),
    )


def make_stored(
    status: StockStatus = StockStatus.OUT_OF_STOCK,
    price: float = 1200.0,
    last_alerted_at: datetime | None = None,
) -> StoredProduct:
    return StoredProduct(
        id=1,
        retailer="LDLC",
        name="ASUS TUF Gaming RTX 5080 OC",
        url="https://ldlc.com/fiche/PB0001.html",
        gpu_family="RTX_5080",
        status=status,
        price_eur=price,
        availability_text="Rupture",
        brand="ASUS",
        seller=None,
        first_seen=datetime.utcnow() - timedelta(days=1),
        last_seen=datetime.utcnow(),
        last_alerted_at=last_alerted_at,
    )


class TestShouldAlert:
    def test_new_product_in_stock_triggers_alert(self, sample_config):
        product = make_product(StockStatus.IN_STOCK, 1200.0)
        do_alert, reason = should_alert(product, None, True, sample_config)
        assert do_alert is True
        assert "new" in reason.lower()

    def test_new_product_out_of_stock_no_alert(self, sample_config):
        product = make_product(StockStatus.OUT_OF_STOCK, 1200.0)
        do_alert, reason = should_alert(product, None, True, sample_config)
        assert do_alert is False

    def test_status_transition_triggers_alert(self, sample_config):
        product = make_product(StockStatus.IN_STOCK, 1200.0)
        prev = make_stored(StockStatus.OUT_OF_STOCK, 1200.0)
        do_alert, reason = should_alert(product, prev, False, sample_config)
        assert do_alert is True
        assert "OUT_OF_STOCK" in reason

    def test_no_status_change_no_alert(self, sample_config):
        product = make_product(StockStatus.IN_STOCK, 1200.0)
        prev = make_stored(StockStatus.IN_STOCK, 1200.0)
        do_alert, reason = should_alert(product, prev, False, sample_config)
        assert do_alert is False

    def test_price_above_ceiling_no_alert(self, sample_config):
        # RTX 5080 ceiling is 1500€
        product = make_product(StockStatus.IN_STOCK, 1600.0)
        do_alert, reason = should_alert(product, None, True, sample_config)
        assert do_alert is False
        assert "ceiling" in reason

    def test_price_at_ceiling_triggers_alert(self, sample_config):
        # Exactly at ceiling = allowed
        product = make_product(StockStatus.IN_STOCK, 1500.0)
        do_alert, reason = should_alert(product, None, True, sample_config)
        assert do_alert is True

    def test_preorder_triggers_alert(self, sample_config):
        product = make_product(StockStatus.PREORDER, 1200.0)
        prev = make_stored(StockStatus.OUT_OF_STOCK, 1200.0)
        do_alert, reason = should_alert(product, prev, False, sample_config)
        assert do_alert is True

    def test_backorder_triggers_alert(self, sample_config):
        product = make_product(StockStatus.BACKORDER, 1200.0)
        prev = make_stored(StockStatus.UNKNOWN, 1200.0)
        do_alert, reason = should_alert(product, prev, False, sample_config)
        assert do_alert is True

    def test_price_drop_below_ceiling_triggers(self, sample_config):
        # Was 1600€ (above ceiling 1500€), now 1450€ (below ceiling)
        product = make_product(StockStatus.IN_STOCK, 1450.0)
        prev = make_stored(StockStatus.IN_STOCK, 1600.0)
        do_alert, reason = should_alert(product, prev, False, sample_config)
        assert do_alert is True
        assert "drop" in reason.lower() or "1600" in reason

    def test_product_id_stable(self):
        p1 = make_product()
        p2 = make_product()
        assert p1.product_id == p2.product_id

    def test_alert_key_includes_status(self):
        p_in = make_product(StockStatus.IN_STOCK, 1200.0)
        p_out = make_product(StockStatus.OUT_OF_STOCK, 1200.0)
        assert p_in.alert_key != p_out.alert_key

    def test_alert_key_price_bucketed(self):
        # Prices in same bucket → same key
        p1 = make_product(StockStatus.IN_STOCK, 1200.0)
        p2 = make_product(StockStatus.IN_STOCK, 1205.0)
        assert p1.alert_key == p2.alert_key

        # Different bucket → different key
        p3 = make_product(StockStatus.IN_STOCK, 1210.0)
        assert p1.alert_key != p3.alert_key


@pytest.mark.asyncio
class TestDatabaseDedupe:
    async def test_upsert_new_product(self, db, sample_product):
        prev, is_new = await db.upsert_product(sample_product)
        assert is_new is True
        assert prev is None

    async def test_upsert_existing_product(self, db, sample_product):
        await db.upsert_product(sample_product)
        prev, is_new = await db.upsert_product(sample_product)
        assert is_new is False
        assert prev is not None

    async def test_cooldown_check_no_prior_alert(self, db, sample_product):
        exists = await db.recent_alert_exists(sample_product.alert_key, 3600)
        assert exists is False

    async def test_cooldown_check_recent_alert(self, db, sample_product):
        await db.upsert_product(sample_product)
        await db.mark_alerted(sample_product, "test")
        exists = await db.recent_alert_exists(sample_product.alert_key, 3600)
        assert exists is True

    async def test_cooldown_check_old_alert(self, db, sample_product):
        """An alert older than cooldown should NOT block a new alert."""
        # Insert a product and mark it alerted with an old timestamp
        # We simulate by directly inserting into alert_log
        await db.upsert_product(sample_product)
        import aiosqlite
        old_ts = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        await db.db.execute(
            "INSERT INTO alert_log (product_id, alert_key, alerted_at, message) VALUES (?, ?, ?, ?)",
            (sample_product.product_id, sample_product.alert_key, old_ts, "old alert"),
        )
        await db.db.commit()
        # Cooldown is 3600s (1h), alert is 2h old → should NOT be in cooldown
        exists = await db.recent_alert_exists(sample_product.alert_key, 3600)
        assert exists is False
