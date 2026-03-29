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
  interval_seconds: 300
  jitter_seconds: 60
  cooldown_seconds: 3600

http:
  timeout_seconds: 10
  max_retries: 1
  retry_backoff_base: 1.0
  user_agents:
    - "TestAgent/1.0"

gpu_targets:
  - family: "RTX_5080_FE"
    display_name: "GeForce RTX 5080 Founders Edition"
    price_ceiling_eur: 1119.0
    keywords_include:
      - "RTX 5080"
    keywords_exclude: []

  - family: "RTX_5090_FE"
    display_name: "GeForce RTX 5090 Founders Edition"
    price_ceiling_eur: 2059.0
    keywords_include:
      - "RTX 5090"
    keywords_exclude: []

  - family: "RX_9070_XT_SAPPHIRE_PURE"
    display_name: "Sapphire Pure Radeon RX 9070 XT Gaming OC 16GB"
    price_ceiling_eur: 649.0
    keywords_include:
      - "Sapphire"
      - "Pure"
      - "9070 XT"
    keywords_exclude:
      - "laptop"
      - "portable"

retailers:
  nvidia_fr:
    enabled: true
    name: "NVIDIA France"
    base_url: "https://store.nvidia.com/fr-fr"
    search_urls:
      - "https://api.store.nvidia.com/partner/v1/feinventory?locale=fr-fr"
    use_browser: false
    country: "FR"

  ldlc:
    enabled: true
    name: "LDLC"
    base_url: "https://www.ldlc.com"
    search_urls: []
    use_browser: false
    country: "FR"

  topachat:
    enabled: true
    name: "TopAchat"
    base_url: "https://www.topachat.com"
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
            family="RTX_5080_FE",
            display_name="GeForce RTX 5080 Founders Edition",
            price_ceiling_eur=1119.0,
            keywords_include=["RTX 5080"],
            keywords_exclude=[],
        ),
        GPUTarget(
            family="RTX_5090_FE",
            display_name="GeForce RTX 5090 Founders Edition",
            price_ceiling_eur=2059.0,
            keywords_include=["RTX 5090"],
            keywords_exclude=[],
        ),
        GPUTarget(
            family="RX_9070_XT_SAPPHIRE_PURE",
            display_name="Sapphire Pure Radeon RX 9070 XT Gaming OC 16GB",
            price_ceiling_eur=649.0,
            keywords_include=["Sapphire", "Pure", "9070 XT"],
            keywords_exclude=["laptop", "portable"],
        ),
    ]


@pytest.fixture
def sample_product() -> Product:
    from datetime import datetime
    return Product(
        retailer="NVIDIA France",
        name="GeForce RTX 5080 16GB Founders Edition",
        url="https://store.nvidia.com/fr-fr/geforce/store/gpu/",
        gpu_family="RTX_5080_FE",
        status=StockStatus.OUT_OF_STOCK,
        price_eur=1119.0,
        availability_text="Indisponible",
        brand="NVIDIA",
        seller=None,
        scraped_at=datetime.utcnow(),
    )
