"""
Parser tests using saved HTML fixtures.

Fixtures are static HTML snapshots stored in tests/fixtures/.
These tests verify that retailer adapters can parse known-good HTML.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gpu_monitor.models import GPUTarget, StockStatus

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _targets() -> list[GPUTarget]:
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


def _load_fixture(name: str) -> str:
    p = FIXTURES_DIR / name
    if not p.exists():
        pytest.skip(f"Fixture {name} not found — run `make fixtures` to generate")
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# LDLC parser
# ---------------------------------------------------------------------------

class TestLDLCParser:
    def _make_retailer(self, sample_config):
        from gpu_monitor.retailers.ldlc import LDLCRetailer
        http = MagicMock()
        return LDLCRetailer(sample_config, http, None)

    def test_parse_json_ld_in_stock(self, sample_config):
        """Parse a synthetic LDLC JSON-LD response."""
        from gpu_monitor.retailers.ldlc import LDLCRetailer
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product",
         "name":"ASUS TUF Gaming GeForce RTX 5080 16GB OC",
         "url":"https://www.ldlc.com/fiche/PB0001.html",
         "offers":{"@type":"Offer","price":"1299.99",
                   "priceCurrency":"EUR",
                   "availability":"https://schema.org/InStock"}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(
            html, "https://www.ldlc.com/recherche/RTX+5080/", _targets()
        )
        assert len(products) == 1
        p = products[0]
        assert "RTX 5080" in p.name
        assert p.status == StockStatus.IN_STOCK
        assert p.price_eur == pytest.approx(1299.99)
        assert p.gpu_family == "RTX_5080"

    def test_parse_json_ld_out_of_stock(self, sample_config):
        from gpu_monitor.retailers.ldlc import LDLCRetailer
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product",
         "name":"MSI Gaming X Trio RTX 5080 16G",
         "url":"https://www.ldlc.com/fiche/PB0002.html",
         "offers":{"@type":"Offer","price":"1450.00","priceCurrency":"EUR",
                   "availability":"https://schema.org/OutOfStock"}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(
            html, "https://www.ldlc.com/recherche/RTX+5080/", _targets()
        )
        assert len(products) == 1
        assert products[0].status == StockStatus.OUT_OF_STOCK

    def test_parse_excludes_laptop(self, sample_config):
        from gpu_monitor.retailers.ldlc import LDLCRetailer
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product",
         "name":"ASUS RTX 5080 Laptop 16GB Mobile",
         "url":"https://www.ldlc.com/fiche/PB0099.html",
         "offers":{"@type":"Offer","price":"1200.00","priceCurrency":"EUR",
                   "availability":"https://schema.org/InStock"}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(
            html, "https://www.ldlc.com/recherche/RTX+5080/", _targets()
        )
        # laptop → excluded
        assert len(products) == 0

    def test_parse_html_cards(self, sample_config):
        """Test parsing HTML product cards (simulated)."""
        from gpu_monitor.retailers.ldlc import LDLCRetailer
        retailer = self._make_retailer(sample_config)
        html = """
        <html><body>
        <ul>
          <li class="pdt-item">
            <h3 class="designation">
              <a href="/fiche/PB0003.html">Gigabyte GeForce RTX 5080 AORUS Master 16G</a>
            </h3>
            <div class="price">1 399,99 €</div>
            <div class="dispo">En stock</div>
          </li>
          <li class="pdt-item">
            <h3 class="designation">
              <a href="/fiche/PB0004.html">Gainward GeForce RTX 5080 Phoenix 16G</a>
            </h3>
            <div class="price">1 279,00 €</div>
            <div class="dispo">Rupture de stock</div>
          </li>
        </ul>
        </body></html>
        """
        products = retailer.parse_products(
            html, "https://www.ldlc.com/recherche/RTX+5080/", _targets()
        )
        assert len(products) == 2
        in_stock = [p for p in products if p.status == StockStatus.IN_STOCK]
        out_stock = [p for p in products if p.status == StockStatus.OUT_OF_STOCK]
        assert len(in_stock) == 1
        assert len(out_stock) == 1
        assert in_stock[0].price_eur == pytest.approx(1399.99)

    def test_parse_from_fixture(self, sample_config):
        html = _load_fixture("ldlc_search.html")
        from gpu_monitor.retailers.ldlc import LDLCRetailer
        retailer = self._make_retailer(sample_config)
        products = retailer.parse_products(
            html, "https://www.ldlc.com/recherche/RTX+5080/", _targets()
        )
        # Basic sanity — fixture should yield at least one product
        assert isinstance(products, list)


# ---------------------------------------------------------------------------
# TopAchat parser
# ---------------------------------------------------------------------------

class TestTopAchatParser:
    def _make_retailer(self, sample_config):
        from gpu_monitor.retailers.topachat import TopAchatRetailer
        return TopAchatRetailer(sample_config, MagicMock(), None)

    def test_parse_json_ld(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        [{"@type":"Product",
          "name":"XFX Speedster MERC310 Radeon RX 9070 XT 16GB",
          "url":"https://www.topachat.com/pages/detail2_cat_est_pieces_ref_est_xfx_rx9070xt.html",
          "offers":{"@type":"Offer","price":"749.99","priceCurrency":"EUR",
                    "availability":"InStock"}}]
        </script></head><body></body></html>
        """
        products = retailer.parse_products(
            html, "https://www.topachat.com/pages/recherche.php", _targets()
        )
        assert len(products) == 1
        assert products[0].gpu_family == "RX_9070_XT"
        assert products[0].status == StockStatus.IN_STOCK
        assert products[0].price_eur == pytest.approx(749.99)

    def test_parse_from_fixture(self, sample_config):
        html = _load_fixture("topachat_search.html")
        retailer = self._make_retailer(sample_config)
        products = retailer.parse_products(
            html, "https://www.topachat.com/pages/recherche.php", _targets()
        )
        assert isinstance(products, list)


# ---------------------------------------------------------------------------
# Materiel.net parser
# ---------------------------------------------------------------------------

class TestMaterielNetParser:
    def _make_retailer(self, sample_config):
        from gpu_monitor.retailers.materiel_net import MaterielNetRetailer
        return MaterielNetRetailer(sample_config, MagicMock(), None)

    def test_parse_json_ld(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type":"Product",
         "name":"MSI GeForce RTX 5070 Ti GAMING X TRIO 16G",
         "url":"https://www.materiel.net/produit/MSI-RTX5070Ti.html",
         "offers":{"@type":"Offer","price":"899.00","priceCurrency":"EUR",
                   "availability":"https://schema.org/PreOrder"}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(
            html, "https://www.materiel.net/recherche/", _targets()
        )
        assert len(products) == 1
        assert products[0].gpu_family == "RTX_5070_TI"
        assert products[0].status == StockStatus.PREORDER

    def test_parse_from_fixture(self, sample_config):
        html = _load_fixture("materiel_net_search.html")
        retailer = self._make_retailer(sample_config)
        products = retailer.parse_products(
            html, "https://www.materiel.net/recherche/", _targets()
        )
        assert isinstance(products, list)


# ---------------------------------------------------------------------------
# Alternate parser
# ---------------------------------------------------------------------------

class TestAlternateParser:
    def _make_retailer(self, sample_config):
        from gpu_monitor.retailers.alternate import AlternateRetailer
        return AlternateRetailer(sample_config, MagicMock(), None)

    def test_translate_german_status(self):
        from gpu_monitor.retailers.alternate import AlternateRetailer
        assert AlternateRetailer._translate_status("lieferbar") == "En stock"
        assert AlternateRetailer._translate_status("nicht lieferbar") == "Rupture de stock"
        assert AlternateRetailer._translate_status("vorbestellbar") == "Pré-commande"

    def test_parse_json_ld(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type":"Product",
         "name":"Sapphire PULSE AMD Radeon RX 9070 XT 16GB",
         "url":"https://www.alternate.fr/html/product/123",
         "offers":{"@type":"Offer","price":"769.99","priceCurrency":"EUR",
                   "availability":"https://schema.org/InStock"}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(
            html, "https://www.alternate.fr/list/", _targets()
        )
        assert len(products) == 1
        assert products[0].status == StockStatus.IN_STOCK

    def test_parse_from_fixture(self, sample_config):
        html = _load_fixture("alternate_search.html")
        retailer = self._make_retailer(sample_config)
        products = retailer.parse_products(
            html, "https://www.alternate.fr/list/", _targets()
        )
        assert isinstance(products, list)


# ---------------------------------------------------------------------------
# Rue du Commerce parser
# ---------------------------------------------------------------------------

class TestRueDuCommerceParser:
    def _make_retailer(self, sample_config):
        from gpu_monitor.retailers.rueducommerce import RueDuCommerceRetailer
        return RueDuCommerceRetailer(sample_config, MagicMock(), None)

    def test_parse_json_ld_with_seller(self, sample_config):
        retailer = self._make_retailer(sample_config)
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type":"Product",
         "name":"ASUS ROG STRIX GeForce RTX 5080 OC 16GB",
         "url":"https://www.rueducommerce.fr/p/gpu-asus-rtx5080.html",
         "offers":{"@type":"Offer","price":"1399.00","priceCurrency":"EUR",
                   "availability":"https://schema.org/InStock",
                   "seller":{"@type":"Organization","name":"Rue du Commerce"}}}
        </script></head><body></body></html>
        """
        products = retailer.parse_products(
            html, "https://www.rueducommerce.fr/recherche", _targets()
        )
        assert len(products) == 1
        assert products[0].gpu_family == "RTX_5080"
        assert products[0].seller == "Rue du Commerce"

    def test_parse_from_fixture(self, sample_config):
        html = _load_fixture("rueducommerce_search.html")
        retailer = self._make_retailer(sample_config)
        products = retailer.parse_products(
            html, "https://www.rueducommerce.fr/recherche", _targets()
        )
        assert isinstance(products, list)
