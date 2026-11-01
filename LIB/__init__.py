"""Master library - shared functions for aviation data frameworks."""

from .http import BaseHTTPClient, APIError
from .config import BaseConfig
from .logging_utils import get_logger
from .sheets import GoogleSheetsSink, SheetsSinkError

__all__ = [
    "BaseHTTPClient",
    "APIError",
    "BaseConfig",
    "get_logger",
    "GoogleSheetsSink",
    "SheetsSinkError",
]

__version__ = "1.0.0"
