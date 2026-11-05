"""Configuration for the Airline Fleet Monitor ingestion framework.

No API key is required: the Airline Fleet Monitor API and Data Export Hub
are public, keyless, read-only JSON endpoints (verified live 2026-11-05).
See docs/ARCHITECTURE.md for the verification notes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AFMConfig:
    """Holds Airline Fleet Monitor configuration.

    Attributes:
        base_url: Site base URL; API lives under /api/v1, exports under /data.
        api_base_url: Full API base (https://airlinefleetmonitor.com/api/v1).
        export_url: Bulk airlines export (https://airlinefleetmonitor.com/data/airlines.json).
        timeout_seconds: HTTP timeout per request.
        max_retries: Retries on network errors / 429s.
        spreadsheet_id: "Fleet Intelligence" workbook (default set below).
        user_agent: Identifies this ingestion client to the open-data host.
    """

    base_url: str = "https://airlinefleetmonitor.com"
    api_base_url: str = "https://airlinefleetmonitor.com/api/v1"
    export_url: str = "https://airlinefleetmonitor.com/data/airlines.json"
    timeout_seconds: int = 60
    max_retries: int = 3
    spreadsheet_id: str = "1cTgndcs_1egjtc8ND5cZvjrQPjHLpZeRIllnQTLBKHo"
    user_agent: str = "goaviator-afm-ingestion/1.0 (weekly fleet snapshot; contact via github.com/aviationengineer)"

    @classmethod
    def from_env(cls) -> "AFMConfig":
        return cls(
            base_url=os.getenv("AFM_BASE_URL", "https://airlinefleetmonitor.com").rstrip("/"),
            api_base_url=os.getenv(
                "AFM_API_BASE_URL", "https://airlinefleetmonitor.com/api/v1"
            ).rstrip("/"),
            export_url=os.getenv(
                "AFM_EXPORT_URL",
                "https://airlinefleetmonitor.com/data/airlines.json",
            ),
            timeout_seconds=int(os.getenv("AFM_TIMEOUT", "60")),
            max_retries=int(os.getenv("AFM_MAX_RETRIES", "3")),
            spreadsheet_id=os.getenv(
                "GOOGLE_SHEET_ID", "1cTgndcs_1egjtc8ND5cZvjrQPjHLpZeRIllnQTLBKHo"
            ),
            user_agent=os.getenv(
                "AFM_USER_AGENT",
                "goaviator-afm-ingestion/1.0 (weekly fleet snapshot)",
            ),
        )
