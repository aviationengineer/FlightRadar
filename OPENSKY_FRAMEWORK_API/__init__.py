"""OpenSky Network ingestion framework."""

from .config import OpenSkyConfig
from .models import OpenSkyState
from .opensky_client import OpenSkyClient
from .pipeline import OpenSkyIngestionPipeline, IngestionResult

__all__ = ["OpenSkyConfig", "OpenSkyState", "OpenSkyClient", "OpenSkyIngestionPipeline", "IngestionResult"]
__version__ = "1.0.0"
