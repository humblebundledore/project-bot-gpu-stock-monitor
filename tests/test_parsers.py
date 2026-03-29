"""
Parser tests for retailer adapters.
Fixtures in tests/fixtures/ are static HTML/JSON snapshots.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gpu_monitor.models import GPUTarget, StockStatus

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _targets() -> list[GPUTarget]:
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


def _load_fixture(name: str) -> str:
    p = FIXTURES_DIR / name
    if not p.exists():
        pytest.skip(f"Fixture {name} not found — save a live page snapshot to generate")
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# NVIDIA France — JSON API
# ---------------------------------------------------------------------------

class TestNvidiaFrParser:
    def _make_retailer(self, sample_config):
        from gpu_monitor.retailers.nvidia_fr import NvidiaFrRetailer
        return NvidiaFrRetailer(sample_config, MagicMock(), None)

    def _api_response(self, items: list[dict]) -> str:
        return json.dumps({"success": True, "listMap": items})

    def test_in_stock(self, sample_config):
        retailer = self._make_retailer(sample_config)
        payload = self._api_response([{
            "fe_sku": "NVGFT080T",
            "product_title": "GeForce RTX 5080 16GB Founders Edition",
            "is_active": "true",
            "price": "1119.00",
            "retailers": [{"purchaseLink": "https://store.nvidia.com/fr-fr/buy/rtx5080"}],
        }])
        products = retailer.parse_products(payload, "https://api.store.nvidia.com/...", _targets())
        assert len(products) == 1
        p = products[0]
        assert p.gpu_family == "RTX_5080_FE"
        assert p.status == StockStatus.IN_STOCK
        assert p.price_eur == pytest.approx(1119.0)
        assert p.retailer == "NVIDIA France"

    def test_out_of_stock(self, sample_config):
        retailer = self._make_retailer(sample_config)
        payload = self._api_response([{
            "fe_sku": "NVGFT090T",
            "product_title": "GeForce RTX 5090 32GB Founders Edition",
            "is_active": "false",
            "price": "2059.00",
            "retailers": [],
        }])
        products = retailer.parse_products(payload, "https://api.store.nvidia.com/...", _targets())
        assert len(products) == 1
        assert products[0].gpu_family == "RTX_5090_FE"
        assert products[0].status == StockStatus.OUT_OF_STOCK

    def test_unknown_card_skipped(self, sample_config):
        """Cards not matching any target are ignored."""
        retailer = self._make_retailer(sample_config)
        payload = self._api_response([{
            "fe_sku": "NVGFT040T",
            "product_title": "GeForce RTX 4090 24GB Founders Edition",
            "is_active": "true",
            "price": "1599.00",
            "retailers": [],
        }])
        products = retailer.parse_products(payload, "https://api.store.nvidia.com/...", _targets())
        assert len(products) == 0

    def test_api_failure(self, sample_config):
        retailer = self._make_retailer(sample_config)
        payload = json.dumps({"success": False})
        products = retailer.parse_products(payload, "https://api.store.nvidia.com/...", _targets())
        assert products == []

    def test_malformed_json(self, sample_config):
        retailer = self._make_retailer(sample_config)
        products = retailer.parse_products("not json at all", "https://api.store.nvidia.com/...", _targets())
        assert products == []


# ---------------------------------------------------------------------------
# LDLC — for Sapphire Pure RX 9070 XT
# ---------------------------------------------------------------------------

class TestLDLCParser:
    def _make_retailer(self, sample_config):
        from gpu_monitor.retailers.ldlc import LDLCRetailer
        return LDLCRetailer(sample_config, MagicMock(), None)

    def test_sapphire_pure_in_stock(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product",
         "name":"Sapphire PURE AMD Radeon RX 9070 XT Gaming OC 16 Go",
         "url":"https://www.ldlc.com/fiche/PB0001.html",
         "offers":{"@type":"Offer","price":"649.00",
                   "priceCurrency":"EUR",
                   "availability":"https://schema.org/InStock"}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(html, "https://www.ldlc.com/recherche/RX+9070+XT/", _targets())
        assert len(products) == 1
        p = products[0]
        assert p.gpu_family == "RX_9070_XT_SAPPHIRE_PURE"
        assert p.status == StockStatus.IN_STOCK
        assert p.price_eur == pytest.approx(649.0)
        assert p.brand == "Sapphire"

    def test_sapphire_pulse_not_matched(self, sample_config):
        """Sapphire PULSE should not match — only PURE is targeted."""
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product",
         "name":"Sapphire PULSE AMD Radeon RX 9070 XT 16 Go",
         "url":"https://www.ldlc.com/fiche/PB0002.html",
         "offers":{"@type":"Offer","price":"589.00",
                   "priceCurrency":"EUR",
                   "availability":"https://schema.org/InStock"}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(html, "https://www.ldlc.com/recherche/RX+9070+XT/", _targets())
        assert len(products) == 0

    def test_out_of_stock(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product",
         "name":"Sapphire PURE AMD Radeon RX 9070 XT Gaming OC 16 Go",
         "url":"https://www.ldlc.com/fiche/PB0003.html",
         "offers":{"@type":"Offer","price":"649.00","priceCurrency":"EUR",
                   "availability":"https://schema.org/OutOfStock"}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(html, "https://www.ldlc.com/recherche/RX+9070+XT/", _targets())
        assert len(products) == 1
        assert products[0].status == StockStatus.OUT_OF_STOCK

    def test_parse_html_cards(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><body><ul>
          <li class="pdt-item">
            <h3 class="designation">
              <a href="/fiche/PB0010.html">Sapphire PURE AMD Radeon RX 9070 XT Gaming OC 16 Go</a>
            </h3>
            <div class="price">649,00 \u20ac</div>
            <div class="dispo">En stock</div>
          </li>
          <li class="pdt-item">
            <h3 class="designation">
              <a href="/fiche/PB0011.html">XFX Speedster RX 9070 XT 16 Go</a>
            </h3>
            <div class="price">699,00 \u20ac</div>
            <div class="dispo">En stock</div>
          </li>
        </ul></body></html>
        """
        products = retailer.parse_products(html, "https://www.ldlc.com/recherche/RX+9070+XT/", _targets())
        # Only the Sapphire Pure matches
        assert len(products) == 1
        assert products[0].gpu_family == "RX_9070_XT_SAPPHIRE_PURE"

    def test_parse_from_fixture(self, sample_config):
        html = _load_fixture("ldlc_search.html")
        retailer = self._make_retailer(sample_config)
        products = retailer.parse_products(html, "https://www.ldlc.com/recherche/RX+9070+XT/", _targets())
        assert isinstance(products, list)


# ---------------------------------------------------------------------------
# TopAchat — for Sapphire Pure RX 9070 XT
# ---------------------------------------------------------------------------

class TestTopAchatParser:
    def _make_retailer(self, sample_config):
        from gpu_monitor.retailers.topachat import TopAchatRetailer
        return TopAchatRetailer(sample_config, MagicMock(), None)

    def test_sapphire_pure_in_stock(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        [{"@type":"Product",
          "name":"Sapphire PURE AMD Radeon RX 9070 XT Gaming OC 16GB",
          "url":"https://www.topachat.com/pages/detail2_cat_est_pieces_ref_est_sapphire_pure_9070xt.html",
          "offers":{"@type":"Offer","price":"649.00","priceCurrency":"EUR",
                    "availability":"InStock"}}]
        </script></head><body></body></html>
        """
        products = retailer.parse_products(html, "https://www.topachat.com/pages/recherche.php", _targets())
        assert len(products) == 1
        assert products[0].gpu_family == "RX_9070_XT_SAPPHIRE_PURE"
        assert products[0].status == StockStatus.IN_STOCK

    def test_sapphire_pulse_not_matched(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        [{"@type":"Product",
          "name":"Sapphire PULSE AMD Radeon RX 9070 XT 16GB",
          "url":"https://www.topachat.com/pages/detail2_cat_est_pieces_ref_est_sapphire_pulse_9070xt.html",
          "offers":{"@type":"Offer","price":"589.00","priceCurrency":"EUR",
                    "availability":"InStock"}}]
        </script></head><body></body></html>
        """
        products = retailer.parse_products(html, "https://www.topachat.com/pages/recherche.php", _targets())
        assert len(products) == 0

    def test_parse_from_fixture(self, sample_config):
        html = _load_fixture("topachat_search.html")
        retailer = self._make_retailer(sample_config)
        products = retailer.parse_products(html, "https://www.topachat.com/pages/recherche.php", _targets())
        assert isinstance(products, list)
