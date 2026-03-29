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

    def test_out_of_stock_indisponible(self):
        assert normalize_status("Indisponible") == StockStatus.OUT_OF_STOCK

    def test_preorder_french(self):
        assert normalize_status("Pré-commande") == StockStatus.PREORDER

    def test_backorder_sur_commande(self):
        assert normalize_status("Sur commande") == StockStatus.BACKORDER

    def test_unknown_empty(self):
        assert normalize_status("") == StockStatus.UNKNOWN

    def test_case_insensitive(self):
        assert normalize_status("EN STOCK") == StockStatus.IN_STOCK

    def test_in_stock_expedie_sous_24h(self):
        assert normalize_status("Expédié sous 24h") == StockStatus.IN_STOCK


class TestMatchGPUFamily:
    def test_rtx5080_fe_matches(self, gpu_targets):
        t = match_gpu_family("GeForce RTX 5080 16GB Founders Edition", gpu_targets)
        assert t is not None
        assert t.family == "RTX_5080_FE"

    def test_rtx5080_fe_short_name(self, gpu_targets):
        t = match_gpu_family("RTX 5080 FE", gpu_targets)
        assert t is not None
        assert t.family == "RTX_5080_FE"

    def test_rtx5090_fe_matches(self, gpu_targets):
        t = match_gpu_family("GeForce RTX 5090 32GB Founders Edition", gpu_targets)
        assert t is not None
        assert t.family == "RTX_5090_FE"

    def test_sapphire_pure_matches(self, gpu_targets):
        t = match_gpu_family("Sapphire PURE AMD Radeon RX 9070 XT Gaming OC 16 Go", gpu_targets)
        assert t is not None
        assert t.family == "RX_9070_XT_SAPPHIRE_PURE"

    def test_sapphire_pure_uppercase(self, gpu_targets):
        t = match_gpu_family("SAPPHIRE PURE RADEON RX 9070 XT GAMING OC 16GB", gpu_targets)
        assert t is not None
        assert t.family == "RX_9070_XT_SAPPHIRE_PURE"

    def test_sapphire_pulse_no_match(self, gpu_targets):
        """PULSE != PURE — should not match."""
        t = match_gpu_family("Sapphire PULSE AMD Radeon RX 9070 XT 16 Go", gpu_targets)
        assert t is None

    def test_rx9070_non_xt_no_match(self, gpu_targets):
        t = match_gpu_family("PowerColor Fighter RX 9070 16GB", gpu_targets)
        assert t is None

    def test_other_rx9070xt_brand_no_match(self, gpu_targets):
        """Other AIB brands don't match — only Sapphire Pure is targeted."""
        t = match_gpu_family("XFX Speedster MERC RX 9070 XT 16GB", gpu_targets)
        assert t is None

    def test_no_match_unrelated(self, gpu_targets):
        t = match_gpu_family("Samsung 980 Pro 1TB NVMe SSD", gpu_targets)
        assert t is None

    def test_sapphire_pure_laptop_excluded(self, gpu_targets):
        t = match_gpu_family("Sapphire PURE RX 9070 XT laptop", gpu_targets)
        assert t is None


class TestDetectBrand:
    def test_asus(self):
        assert detect_brand("ASUS TUF Gaming RTX 5080") == "ASUS"

    def test_msi(self):
        assert detect_brand("MSI Gaming X Trio RTX 5080") == "MSI"

    def test_sapphire(self):
        assert detect_brand("Sapphire PURE AMD Radeon RX 9070 XT") == "Sapphire"

    def test_xfx(self):
        assert detect_brand("XFX Speedster MERC RX 9070 XT") == "XFX"

    def test_no_brand(self):
        assert detect_brand("Generic RTX 5080 OC") is None


class TestParsePrice:
    def test_basic_euro(self):
        assert parse_price("1 299,99 \u20ac") == pytest.approx(1299.99)

    def test_dot_comma(self):
        assert parse_price("1.299,99 \u20ac") == pytest.approx(1299.99)

    def test_no_cents(self):
        assert parse_price("999 \u20ac") == pytest.approx(999.0)

    def test_prefix_euro(self):
        assert parse_price("\u20ac 1299.00") == pytest.approx(1299.0)

    def test_none_on_empty(self):
        assert parse_price("") is None

    def test_price_with_text(self):
        assert parse_price("Prix: 649,00 \u20ac") == pytest.approx(649.0)

    def test_msrp_prices(self):
        assert parse_price("1119.00 \u20ac") == pytest.approx(1119.0)
        assert parse_price("2059.00 \u20ac") == pytest.approx(2059.0)
        assert parse_price("649.00 \u20ac") == pytest.approx(649.0)


class TestShouldExclude:
    def test_laptop_excluded(self):
        assert should_exclude("ASUS ROG RTX 5080 Laptop 16GB") is True

    def test_ordinateur_excluded(self):
        assert should_exclude("Ordinateur Gaming RTX 5080") is True

    def test_waterblock_excluded(self):
        assert should_exclude("EK Waterblock RTX 5080") is True

    def test_sapphire_pure_not_excluded(self):
        assert should_exclude("Sapphire PURE AMD Radeon RX 9070 XT Gaming OC 16 Go") is False

    def test_founders_not_excluded(self):
        assert should_exclude("GeForce RTX 5080 16GB Founders Edition") is False

    def test_riser_excluded(self):
        assert should_exclude("PCIe riser RTX 5080 bracket") is True

    def test_refurb_excluded(self):
        assert should_exclude("RTX 5080 refurb occasion") is True
