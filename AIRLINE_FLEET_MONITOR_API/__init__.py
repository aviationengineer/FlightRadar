"""Airline Fleet Monitor ingestion framework."""

from .config import AFMConfig
from .models import AirlineFleet

__all__ = ["AFMConfig", "AirlineFleet"]
__version__ = "1.0.0"
