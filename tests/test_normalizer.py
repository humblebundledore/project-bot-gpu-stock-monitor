"""Tests for the normalizer module."""

from __future__ import annotations

import pytest

from gpu_monitor.normalizer import (
    detect_brand,
    match_gpu_family,
    normalize_status,
    parse_price,
    should_exclude,
)
from gpu_monitor.models import GPUTarget, StockStatus


# ---------------------------------------------------------------------------
# Status normalization
# ---------------------------------------------------------------------------

class TestNormalizeStatus:
    def test_in_stock_french(self):
        assert normalize_status("En stock") == StockStatus.IN_STOCK

    def test_in_stock_english(self):
        assert normalize_status("In Stock") == StockStatus.IN_STOCK

    def test_in_stock_disponible(self):
        assert normalize_status("Disponible") == StockStatus.IN_STOCK

    def test_in_stock_add_to_cart(self):
        assert normalize_status("Ajouter au panier") == StockStatus.IN_STOCK

    def test_out_of_stock_rupture(self):
        assert normalize_status("Rupture de stock") == StockStatus.OUT_OF_STOCK

    def test_out_of_stock_epuise(self):
        assert normalize_status("Épuisé") == StockStatus.OUT_OF_STOCK

    def test_out_of_stock_indisponible(self):
        assert normalize_status("Indisponible") == StockStatus.OUT_OF_STOCK

    def test_preorder_french(self):
        assert normalize_status("Pré-commande") == StockStatus.PREORDER

    def test_preorder_english(self):
        assert normalize_status("Preorder") == StockStatus.PREORDER

    def test_backorder_sur_commande(self):
        assert normalize_status("Sur commande") == StockStatus.BACKORDER

    def test_backorder_expedi_sous(self):
        assert normalize_status("Expédié sous 10 jours") == StockStatus.BACKORDER

    def test_unknown_empty(self):
        assert normalize_status("") == StockStatus.UNKNOWN

    def test_unknown_garbage(self):
        assert normalize_status("blah blah") == StockStatus.UNKNOWN

    def test_case_insensitive(self):
        assert normalize_status("EN STOCK") == StockStatus.IN_STOCK

    def test_in_stock_expedie_sous_24h(self):
        assert normalize_status("Expédié sous 24h") == StockStatus.IN_STOCK

    def test_schema_org_in_stock(self):
        assert normalize_status("En stock") == StockStatus.IN_STOCK


# ---------------------------------------------------------------------------
# GPU family matching
# ---------------------------------------------------------------------------

class TestMatchGPUFamily:
    def test_rtx5080_basic(self, gpu_targets):
        t = match_gpu_family("ASUS TUF Gaming GeForce RTX 5080 16GB OC", gpu_targets)
        assert t is not None
        assert t.family == "RTX_5080"

    def test_rtx5080_short(self, gpu_targets):
        t = match_gpu_family("MSI RTX 5080 VENTUS 3X", gpu_targets)
        assert t is not None
        assert t.family == "RTX_5080"

    def test_rx9070xt(self, gpu_targets):
        t = match_gpu_family("Sapphire PULSE Radeon RX 9070 XT 16GB", gpu_targets)
        assert t is not None
        assert t.family == "RX_9070_XT"

    def test_rtx5070ti(self, gpu_targets):
        t = match_gpu_family("Gigabyte AORUS RTX 5070 Ti MASTER 16GB", gpu_targets)
        assert t is not None
        assert t.family == "RTX_5070_TI"

    def test_no_match(self, gpu_targets):
        t = match_gpu_family("Samsung 980 Pro 1TB NVMe SSD", gpu_targets)
        assert t is None

    def test_rtx5080_laptop_excluded(self, gpu_targets):
        t = match_gpu_family("ASUS ROG RTX 5080 laptop 16GB", gpu_targets)
        assert t is None

    def test_rtx5080_waterblock_excluded(self, gpu_targets):
        t = match_gpu_family("EK Waterblock RTX 5080 Nickel", gpu_targets)
        assert t is None

    def test_rtx5080_in_pc_excluded(self, gpu_targets):
        # "ordinateur" should exclude
        t = match_gpu_family("Ordinateur Gaming RTX 5080 Desktop", gpu_targets)
        assert t is None

    def test_rx9070_non_xt_no_match(self, gpu_targets):
        """Plain RX 9070 should NOT match RX 9070 XT target."""
        # The RX_9070_XT target requires "RX 9070 XT" as a keyword
        # A product named "RX 9070" without "XT" won't include the required keyword
        t = match_gpu_family("PowerColor Fighter RX 9070 16GB", gpu_targets)
        # "RX 9070 XT" is NOT a substring of "RX 9070 16GB" so it won't match
        assert t is None


# ---------------------------------------------------------------------------
# Brand detection
# ---------------------------------------------------------------------------

class TestDetectBrand:
    def test_asus(self):
        assert detect_brand("ASUS TUF Gaming RTX 5080") == "ASUS"

    def test_msi(self):
        assert detect_brand("MSI Gaming X Trio RTX 5080") == "MSI"

    def test_gigabyte(self):
        assert detect_brand("Gigabyte AORUS Master RTX 5080") == "Gigabyte"

    def test_sapphire(self):
        assert detect_brand("Sapphire PULSE RX 9070 XT") == "Sapphire"

    def test_powercolor(self):
        assert detect_brand("PowerColor Hellhound RX 9070 XT") == "PowerColor"

    def test_unknown(self):
        assert detect_brand("XFX Speedster MERC RX 9070 XT") == "XFX"

    def test_no_brand(self):
        assert detect_brand("Generic RTX 5080 OC") is None


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------

class TestParsePrice:
    def test_basic_euro(self):
        assert parse_price("1 299,99 €") == pytest.approx(1299.99)

    def test_dot_comma(self):
        assert parse_price("1.299,99 €") == pytest.approx(1299.99)

    def test_no_cents(self):
        assert parse_price("999 €") == pytest.approx(999.0)

    def test_prefix_euro(self):
        assert parse_price("€ 1299.00") == pytest.approx(1299.0)

    def test_none_on_empty(self):
        assert parse_price("") is None

    def test_none_on_no_price(self):
        assert parse_price("Rupture de stock") is None

    def test_price_with_text(self):
        assert parse_price("Prix: 849,00 €") == pytest.approx(849.0)

    def test_integer_price(self):
        assert parse_price("1500€") == pytest.approx(1500.0)


# ---------------------------------------------------------------------------
# Exclusion filter
# ---------------------------------------------------------------------------

class TestShouldExclude:
    def test_laptop_excluded(self):
        assert should_exclude("ASUS ROG RTX 5080 Laptop 16GB") is True

    def test_ordinateur_excluded(self):
        assert should_exclude("Ordinateur Gaming RTX 5080") is True

    def test_waterblock_excluded(self):
        assert should_exclude("EK Waterblock RTX 5080") is True

    def test_water_block_excluded(self):
        assert should_exclude("Corsair water block RTX 5080") is True

    def test_normal_card_not_excluded(self):
        assert should_exclude("ASUS TUF Gaming RTX 5080 16GB OC") is False

    def test_riser_excluded(self):
        assert should_exclude("PCIe riser RTX 5080 bracket") is True

    def test_refurb_excluded(self):
        assert should_exclude("RTX 5080 refurb occasion") is True
