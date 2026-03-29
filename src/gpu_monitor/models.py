"""Data models for GPU Stock Monitor."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class StockStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    PREORDER = "PREORDER"
    BACKORDER = "BACKORDER"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"


# Statuses that warrant an alert when transitioning FROM an inactive state
ALERTABLE_STATUSES = {StockStatus.IN_STOCK, StockStatus.PREORDER, StockStatus.BACKORDER}
# Inactive statuses — no alert desired
INACTIVE_STATUSES = {StockStatus.OUT_OF_STOCK, StockStatus.UNKNOWN}


@dataclass
class Product:
    """A single GPU listing scraped from a retailer."""

    retailer: str
    name: str
    url: str
    gpu_family: str           # e.g. RTX_5080
    status: StockStatus
    price_eur: Optional[float]
    availability_text: str    # raw string from retailer
    brand: Optional[str]      # ASUS, MSI, etc.
    seller: Optional[str]     # marketplace seller if applicable
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def product_id(self) -> str:
        """Stable hash based on retailer + canonical URL."""
        raw = f"{self.retailer}::{self.url}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    @property
    def alert_key(self) -> str:
        """Dedup key: same product + status + price bucket."""
        price_bucket = int(self.price_eur or 0) // 10 * 10  # round to nearest 10€
        return f"{self.product_id}::{self.status}::{price_bucket}"


@dataclass
class StoredProduct:
    """Persisted product record from the database."""

    id: int
    retailer: str
    name: str
    url: str
    gpu_family: str
    status: StockStatus
    price_eur: Optional[float]
    availability_text: str
    brand: Optional[str]
    seller: Optional[str]
    first_seen: datetime
    last_seen: datetime
    last_alerted_at: Optional[datetime]

    @property
    def product_id(self) -> str:
        raw = f"{self.retailer}::{self.url}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]


@dataclass
class GPUTarget:
    family: str
    display_name: str
    price_ceiling_eur: float
    keywords_include: list[str]
    keywords_exclude: list[str]


@dataclass
class RetailerConfig:
    key: str
    name: str
    base_url: str
    search_urls: list[str]
    use_browser: bool
    country: str
    ships_to_france: bool = True
    enabled: bool = True
