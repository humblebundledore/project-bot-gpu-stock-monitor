"""pytest configuration and shared fixtures."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from gpu_monitor.config import AppConfig, reload_config
from gpu_monitor.db import Database
from gpu_monitor.models import GPUTarget, StockStatus, Product

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def sample_config(tmp_path) -> AppConfig:
    """Minimal AppConfig for testing."""
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
discord:
  token: "test-token"
  guild_id: "123456789"
  alert_channel: "test-channel"
  auto_create_channel: false
  daily_digest: false

database:
  path: ":memory:"

polling:
  interval_seconds: 900
  jitter_seconds: 120
  cooldown_seconds: 3600

http:
  timeout_seconds: 10
  max_retries: 1
  retry_backoff_base: 1.0
  user_agents:
    - "TestAgent/1.0"

gpu_targets:
  - family: "RTX_5080"
    display_name: "GeForce RTX 5080 16GB"
    price_ceiling_eur: 1500.0
    keywords_include:
      - "RTX 5080"
    keywords_exclude:
      - "laptop"
      - "waterblock"
      - "ordinateur"

  - family: "RX_9070_XT"
    display_name: "Radeon RX 9070 XT 16GB"
    price_ceiling_eur: 850.0
    keywords_include:
      - "RX 9070 XT"
    keywords_exclude:
      - "laptop"

  - family: "RTX_5070_TI"
    display_name: "GeForce RTX 5070 Ti 16GB"
    price_ceiling_eur: 950.0
    keywords_include:
      - "RTX 5070 Ti"
    keywords_exclude:
      - "laptop"

preferred_brands:
  - ASUS
  - MSI

retailers:
  ldlc:
    enabled: true
    name: "LDLC"
    base_url: "https://www.ldlc.com"
    search_urls: []
    use_browser: false
    country: "FR"

logging:
  level: "DEBUG"
  format: "text"
  file: ""
""")
    return reload_config(config_yaml)


@pytest_asyncio.fixture
async def db(tmp_path) -> Database:
    """In-memory test database."""
    d = Database(str(tmp_path / "test.db"))
    await d.connect()
    yield d
    await d.close()


@pytest.fixture
def gpu_targets() -> list[GPUTarget]:
    return [
        GPUTarget(
            family="RTX_5080",
            display_name="GeForce RTX 5080 16GB",
            price_ceiling_eur=1500.0,
            keywords_include=["RTX 5080"],
            keywords_exclude=["laptop", "waterblock", "ordinateur"],
        ),
        GPUTarget(
            family="RX_9070_XT",
            display_name="Radeon RX 9070 XT 16GB",
            price_ceiling_eur=850.0,
            keywords_include=["RX 9070 XT"],
            keywords_exclude=["laptop"],
        ),
        GPUTarget(
            family="RTX_5070_TI",
            display_name="GeForce RTX 5070 Ti 16GB",
            price_ceiling_eur=950.0,
            keywords_include=["RTX 5070 Ti"],
            keywords_exclude=["laptop"],
        ),
    ]


@pytest.fixture
def sample_product() -> Product:
    from datetime import datetime
    return Product(
        retailer="LDLC",
        name="ASUS TUF Gaming GeForce RTX 5080 16GB OC",
        url="https://www.ldlc.com/fiche/PB00000001.html",
        gpu_family="RTX_5080",
        status=StockStatus.IN_STOCK,
        price_eur=1299.99,
        availability_text="En stock",
        brand="ASUS",
        seller=None,
        scraped_at=datetime.utcnow(),
    )
