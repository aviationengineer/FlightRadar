"""AirLabs Fleet API ingestion framework."""

from .config import AirlabsConfig, TOP_AIRLINES_IATA
from .airlabs_client import (
    AirlabsClient,
    AirlabsAPIError,
    AirlabsRateLimitError,
)
from .models import FleetAircraft
from .pipeline import AirlabsFleetPipeline, IngestionResult
from .sheets_sink import AirlabsSheetsSink

__all__ = [
    "AirlabsConfig",
    "TOP_AIRLINES_IATA",
    "AirlabsClient",
    "AirlabsAPIError",
    "AirlabsRateLimitError",
    "FleetAircraft",
    "AirlabsFleetPipeline",
    "IngestionResult",
    "AirlabsSheetsSink",
]

__version__ = "1.0.0"
