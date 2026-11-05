"""Skylink API ingestion framework."""

from .config import SkylinkConfig, MISSING_KEY_MESSAGE
from .skylink_client import SkylinkClient, SkylinkAPIError
from .models import AircraftObservation, RegistrationDetail, Airline
from .pipeline import SkylinkIngestionPipeline, IngestionResult
from .sheets_sink import SkylinkSheetsSink

__all__ = [
    "SkylinkConfig",
    "MISSING_KEY_MESSAGE",
    "SkylinkClient",
    "SkylinkAPIError",
    "AircraftObservation",
    "RegistrationDetail",
    "Airline",
    "SkylinkIngestionPipeline",
    "IngestionResult",
    "SkylinkSheetsSink",
]

__version__ = "1.0.0"
