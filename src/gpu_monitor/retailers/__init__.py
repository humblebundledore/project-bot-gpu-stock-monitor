"""Retailer adapters package."""

from .base import BaseRetailer
from .nvidia_fr import NvidiaFrRetailer
from .ldlc import LDLCRetailer
from .topachat import TopAchatRetailer

__all__ = [
    "BaseRetailer",
    "NvidiaFrRetailer",
    "LDLCRetailer",
    "TopAchatRetailer",
]

RETAILER_MAP = {
    "nvidia_fr": NvidiaFrRetailer,
    "ldlc": LDLCRetailer,
    "topachat": TopAchatRetailer,
}
