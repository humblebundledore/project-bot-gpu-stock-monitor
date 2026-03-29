"""SQLite persistence layer via aiosqlite."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

import aiosqlite

from .models import Product, StockStatus, StoredProduct

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id        TEXT NOT NULL,
    retailer          TEXT NOT NULL,
    name              TEXT NOT NULL,
    url               TEXT NOT NULL,
    gpu_family        TEXT NOT NULL,
    status            TEXT NOT NULL,
    price_eur         REAL,
    availability_text TEXT NOT NULL DEFAULT '',
    brand             TEXT,
    seller            TEXT,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    last_alerted_at   TEXT,
    UNIQUE(product_id)
);

CREATE INDEX IF NOT EXISTS idx_products_gpu_family ON products(gpu_family);
CREATE INDEX IF NOT EXISTS idx_products_retailer ON products(retailer);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);

CREATE TABLE IF NOT EXISTS alert_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  TEXT NOT NULL,
    alert_key   TEXT NOT NULL,
    alerted_at  TEXT NOT NULL,
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_log_product ON alert_log(product_id);
CREATE INDEX IF NOT EXISTS idx_alert_log_key ON alert_log(alert_key);
"""


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    async def upsert_product(self, product: Product) -> tuple[StoredProduct | None, bool]:
        """
        Insert or update a product.
        Returns (previous_record, is_new).
        """
        async with self._lock:
            now_iso = _iso(product.scraped_at)

            # Check existing
            cursor = await self.db.execute(
                "SELECT * FROM products WHERE product_id = ?",
                (product.product_id,),
            )
            row = await cursor.fetchone()

            if row is None:
                # New product
                await self.db.execute(
                    """
                    INSERT INTO products
                        (product_id, retailer, name, url, gpu_family,
                         status, price_eur, availability_text, brand, seller,
                         first_seen, last_seen, last_alerted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        product.product_id,
                        product.retailer,
                        product.name,
                        product.url,
                        product.gpu_family,
                        product.status.value,
                        product.price_eur,
                        product.availability_text,
                        product.brand,
                        product.seller,
                        now_iso,
                        now_iso,
                    ),
                )
                await self.db.commit()
                return None, True

            prev = _row_to_stored(row)
            # Update existing
            await self.db.execute(
                """
                UPDATE products SET
                    name = ?,
                    status = ?,
                    price_eur = ?,
                    availability_text = ?,
                    brand = ?,
                    seller = ?,
                    last_seen = ?
                WHERE product_id = ?
                """,
                (
                    product.name,
                    product.status.value,
                    product.price_eur,
                    product.availability_text,
                    product.brand,
                    product.seller,
                    now_iso,
                    product.product_id,
                ),
            )
            await self.db.commit()
            return prev, False

    async def mark_alerted(self, product: Product, message: str = "") -> None:
        async with self._lock:
            now_iso = _iso(product.scraped_at)
            await self.db.execute(
                "UPDATE products SET last_alerted_at = ? WHERE product_id = ?",
                (now_iso, product.product_id),
            )
            await self.db.execute(
                "INSERT INTO alert_log (product_id, alert_key, alerted_at, message) VALUES (?, ?, ?, ?)",
                (product.product_id, product.alert_key, now_iso, message),
            )
            await self.db.commit()

    async def get_last_alerted_at(self, product: Product) -> datetime | None:
        cursor = await self.db.execute(
            "SELECT last_alerted_at FROM products WHERE product_id = ?",
            (product.product_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _parse_dt(row["last_alerted_at"])

    async def list_products(
        self,
        gpu_family: str | None = None,
        retailer: str | None = None,
        status: StockStatus | None = None,
    ) -> list[StoredProduct]:
        conditions = []
        params: list = []
        if gpu_family:
            conditions.append("gpu_family = ?")
            params.append(gpu_family)
        if retailer:
            conditions.append("retailer = ?")
            params.append(retailer)
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cursor = await self.db.execute(
            f"SELECT * FROM products {where} ORDER BY last_seen DESC",
            params,
        )
        rows = await cursor.fetchall()
        return [_row_to_stored(r) for r in rows]

    async def get_product_by_id(self, product_id: str) -> StoredProduct | None:
        cursor = await self.db.execute(
            "SELECT * FROM products WHERE product_id = ?", (product_id,)
        )
        row = await cursor.fetchone()
        return _row_to_stored(row) if row else None

    async def recent_alert_exists(self, alert_key: str, cooldown_seconds: int) -> bool:
        """Check if an alert with this key was sent within the cooldown window."""
        cursor = await self.db.execute(
            """
            SELECT alerted_at FROM alert_log
            WHERE alert_key = ?
            ORDER BY alerted_at DESC
            LIMIT 1
            """,
            (alert_key,),
        )
        row = await cursor.fetchone()
        if not row:
            return False
        last = _parse_dt(row["alerted_at"])
        if not last:
            return False
        now = datetime.utcnow()
        age = (now - last).total_seconds()
        return age < cooldown_seconds


def _row_to_stored(row: aiosqlite.Row) -> StoredProduct:
    return StoredProduct(
        id=row["id"],
        retailer=row["retailer"],
        name=row["name"],
        url=row["url"],
        gpu_family=row["gpu_family"],
        status=StockStatus(row["status"]),
        price_eur=row["price_eur"],
        availability_text=row["availability_text"] or "",
        brand=row["brand"],
        seller=row["seller"],
        first_seen=datetime.fromisoformat(row["first_seen"]),
        last_seen=datetime.fromisoformat(row["last_seen"]),
        last_alerted_at=_parse_dt(row["last_alerted_at"]),
    )


@asynccontextmanager
async def open_db(path: str) -> AsyncIterator[Database]:
    db = Database(path)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
