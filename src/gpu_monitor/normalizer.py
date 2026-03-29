"""
Product normalization: GPU family matching, brand detection, status normalization.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import GPUTarget, StockStatus


# ---------------------------------------------------------------------------
# Status normalization
# ---------------------------------------------------------------------------

_STATUS_PATTERNS: list[tuple[StockStatus, list[str]]] = [
    (StockStatus.IN_STOCK, [
        r"\ben stock\b",
        r"\bdisponible\b",
        r"\blivraison imm[eé]diate\b",
        r"\bajouter au panier\b",
        r"\badd to cart\b",
        r"\bin stock\b",
        r"\bavailable\b",
        r"\bexpédié sous\s*\d+\s*h\b",  # shipped within Xh
        r"\blivré\s+(?:aujourd'hui|demain)\b",
        r"\bexpedié aujourd'hui\b",
    ]),
    (StockStatus.PREORDER, [
        r"\bpré[- ]?commande\b",
        r"\bpreorder\b",
        r"\bpre-order\b",
        r"\bpré-order\b",
        r"\bà paraître\b",
        r"\bcoming soon\b",
        r"\bdisponible le\b",
    ]),
    (StockStatus.BACKORDER, [
        r"\bcommande spéciale\b",
        r"\bsur commande\b",
        r"\bbackorder\b",
        r"\bback[\s-]order\b",
        r"\bdélai\s+\d+",
        r"\bship(?:s|ped)?\s+in\s+\d+\s+(?:day|week|business)",
        r"\bexpédié sous\s*\d+\s+(?:jour|semaine|week|day)",
        r"\blivraison\s+(?:sous\s+)?\d+\s+(?:jour|semaine)",
        r"\bestimé\s*:\s*\d",
        r"\bà commander\b",
    ]),
    (StockStatus.OUT_OF_STOCK, [
        r"\brupture de stock\b",
        r"\bépuisé\b",
        r"\bepuis[eé]\b",
        r"\bout of stock\b",
        r"\bunavailable\b",
        r"\bindisponible\b",
        r"\bnon disponible\b",
        r"\btemporairement indisponible\b",
        r"\bsold out\b",
    ]),
]

# Compiled for performance
_COMPILED_PATTERNS: list[tuple[StockStatus, list[re.Pattern]]] = [
    (status, [re.compile(p, re.IGNORECASE) for p in patterns])
    for status, patterns in _STATUS_PATTERNS
]


def normalize_status(text: str) -> StockStatus:
    """
    Map a free-form availability string to a StockStatus enum value.
    Returns UNKNOWN if no pattern matches.
    """
    if not text:
        return StockStatus.UNKNOWN
    cleaned = text.strip().lower()
    for status, patterns in _COMPILED_PATTERNS:
        for pat in patterns:
            if pat.search(cleaned):
                return status
    return StockStatus.UNKNOWN


# ---------------------------------------------------------------------------
# GPU family matching
# ---------------------------------------------------------------------------

def match_gpu_family(
    product_name: str,
    targets: list[GPUTarget],
) -> Optional[GPUTarget]:
    """
    Return the first GPUTarget whose keywords match the product name,
    respecting include/exclude rules.
    """
    name_lower = product_name.lower()
    for target in targets:
        # All include keywords must appear
        if not all(kw.lower() in name_lower for kw in target.keywords_include):
            continue
        # No exclude keyword must appear
        if any(kw.lower() in name_lower for kw in target.keywords_exclude):
            continue
        return target
    return None


# ---------------------------------------------------------------------------
# Brand detection
# ---------------------------------------------------------------------------

_KNOWN_BRANDS = [
    "ASUS", "MSI", "Gigabyte", "Sapphire", "PowerColor", "XFX",
    "Gainward", "Zotac", "PNY", "Palit", "Inno3D", "EVGA",
    "Colorful", "GALAX", "KFA2",
]

_BRAND_PATTERNS: list[tuple[str, re.Pattern]] = [
    (brand, re.compile(r"\b" + re.escape(brand) + r"\b", re.IGNORECASE))
    for brand in _KNOWN_BRANDS
]


def detect_brand(product_name: str) -> Optional[str]:
    """Extract brand name from product title, returns canonical capitalized form."""
    for brand, pat in _BRAND_PATTERNS:
        if pat.search(product_name):
            return brand
    return None


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(
    r"(\d{1,4}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?)\s*[€$£]|"
    r"[€$£]\s*(\d{1,4}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?)"
)


def parse_price(text: str) -> Optional[float]:
    """
    Extract the first price from a string and return as a float (EUR).
    Handles formats like: 1 299,99 € / 1.299,99€ / €1299.00
    """
    if not text:
        return None
    match = _PRICE_RE.search(text.strip())
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    if not raw:
        return None
    # Normalize: remove spaces, convert comma decimal
    raw = raw.replace(" ", "").replace("\u00a0", "")
    # European format: 1.299,99 → 1299.99
    if "," in raw and "." in raw:
        # Thousands dot, comma decimal
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        # Could be decimal comma: 1299,99 → 1299.99
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Exclusion filter
# ---------------------------------------------------------------------------

_EXCLUDE_PATTERNS = [
    re.compile(r"\blaptop\b", re.IGNORECASE),
    re.compile(r"\bportable\b", re.IGNORECASE),
    re.compile(r"\bmobile\b", re.IGNORECASE),
    re.compile(r"\bwaterblock\b", re.IGNORECASE),
    re.compile(r"\bwater[\s-]block\b", re.IGNORECASE),
    re.compile(r"\bmonoblock\b", re.IGNORECASE),
    re.compile(r"\brefurb\b", re.IGNORECASE),
    re.compile(r"\breconditionn[eé]\b", re.IGNORECASE),
    re.compile(r"\boccasion\b", re.IGNORECASE),
    re.compile(r"\bPC complet\b", re.IGNORECASE),
    re.compile(r"\bordinateur\b", re.IGNORECASE),
    re.compile(r"\btour\b.*\bRTX\b", re.IGNORECASE),
    re.compile(r"\bRTX\b.*\btour\b", re.IGNORECASE),
    re.compile(r"\badaptateur\b", re.IGNORECASE),
    re.compile(r"\briser\b", re.IGNORECASE),
    re.compile(r"\bsupport\b.*\bcarte\b", re.IGNORECASE),
    re.compile(r"\banti-sagg\b", re.IGNORECASE),
]


def should_exclude(product_name: str) -> bool:
    """Return True if the product name matches any global exclusion rule."""
    for pat in _EXCLUDE_PATTERNS:
        if pat.search(product_name):
            return True
    return False
