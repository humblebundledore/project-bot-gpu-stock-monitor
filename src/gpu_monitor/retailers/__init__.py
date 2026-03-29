"""Retailer adapters package."""

from .base import BaseRetailer
from .ldlc import LDLCRetailer
from .topachat import TopAchatRetailer
from .materiel_net import MaterielNetRetailer
from .alternate import AlternateRetailer
from .rueducommerce import RueDuCommerceRetailer

__all__ = [
    "BaseRetailer",
    "LDLCRetailer",
    "TopAchatRetailer",
    "MaterielNetRetailer",
    "AlternateRetailer",
    "RueDuCommerceRetailer",
]

RETAILER_MAP = {
    "ldlc": LDLCRetailer,
    "topachat": TopAchatRetailer,
    "materiel_net": MaterielNetRetailer,
    "alternate": AlternateRetailer,
    "rueducommerce": RueDuCommerceRetailer,
}
