"""FlightRadar24 ingestion framework."""

from .config import FR24Config
from .fr24_client import FlightRadar24Client, FR24APIError
from .models import Flight
from .pipeline import FlightIngestionPipeline, IngestionResult
from .sheets_sink import GoogleSheetsSink

__all__ = [
    "FR24Config",
    "FlightRadar24Client",
    "FR24APIError",
    "Flight",
    "FlightIngestionPipeline",
    "IngestionResult",
    "GoogleSheetsSink",
]

__version__ = "1.0.0"
