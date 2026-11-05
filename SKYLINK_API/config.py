"""Configuration for the Skylink API ingestion framework.

Skylink is hosted on RapidAPI (skylink-api.p.rapidapi.com). Free Basic tier:
1,000 requests/month, no credit card required.

Get a free key at https://rapidapi.com/ (search "Skylink") and set
SKYLINK_RAPIDAPI_KEY. Never put a key in code, docs, or the repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Message shown whenever the key is absent. schedule_run.py logs this and
#: exits 0 (graceful skip) instead of erroring loudly.
MISSING_KEY_MESSAGE = (
    "SKYLINK_RAPIDAPI_KEY is not set — get a free RapidAPI key for Skylink "
    "(https://rapidapi.com/ — search 'Skylink', Basic tier is free, "
    "1,000 requests/month, no credit card) and set SKYLINK_RAPIDAPI_KEY."
)

#: Default target airlines for the weekly snapshot. Override with the
#: SKYLINK_AIRLINES env var (comma-separated airline names).
DEFAULT_AIRLINES: tuple[str, ...] = (
    "Air Canada",
    "WestJet",
    "Emirates",
    "Qatar Airways",
    "British Airways",
    "Lufthansa",
    "Air France",
    "KLM",
    "Delta Air Lines",
    "Turkish Airlines",
)


@dataclass(frozen=True)
class SkylinkConfig:
    """Holds Skylink (RapidAPI) configuration.

    Attributes:
        api_key: RapidAPI key for Skylink (X-RapidAPI-Key header).
        base_url: RapidAPI host base URL.
        rapidapi_host: X-RapidAPI-Host header value.
        timeout_seconds: HTTP timeout per request.
        max_pages_per_airline: pagination guard per airline query.
        page_size: records requested per ADS-B page.
        max_registration_lookups: cap on /aircraft/registration lookups
            per run — only spent on aircraft whose operator is unresolved
            from the ADS-B record, so the quota stays small.
        target_airlines: airline names to snapshot each run.
    """

    api_key: str
    base_url: str = "https://skylink-api.p.rapidapi.com"
    rapidapi_host: str = "skylink-api.p.rapidapi.com"
    timeout_seconds: int = 30
    max_pages_per_airline: int = 5
    page_size: int = 100
    max_registration_lookups: int = 25
    target_airlines: tuple[str, ...] = field(default=DEFAULT_AIRLINES)

    @classmethod
    def from_env(cls) -> "SkylinkConfig":
        key = os.getenv("SKYLINK_RAPIDAPI_KEY", "").strip()
        if not key:
            raise ValueError(MISSING_KEY_MESSAGE)
        airlines = tuple(
            a.strip()
            for a in os.getenv("SKYLINK_AIRLINES", "").split(",")
            if a.strip()
        ) or DEFAULT_AIRLINES
        return cls(
            api_key=key,
            base_url=os.getenv(
                "SKYLINK_BASE_URL", "https://skylink-api.p.rapidapi.com"
            ).rstrip("/"),
            rapidapi_host=os.getenv(
                "SKYLINK_RAPIDAPI_HOST", "skylink-api.p.rapidapi.com"
            ),
            timeout_seconds=int(os.getenv("SKYLINK_TIMEOUT", "30")),
            max_pages_per_airline=int(os.getenv("SKYLINK_MAX_PAGES", "5")),
            page_size=int(os.getenv("SKYLINK_PAGE_SIZE", "100")),
            max_registration_lookups=int(os.getenv("SKYLINK_MAX_REG_LOOKUPS", "25")),
            target_airlines=airlines,
        )

    @classmethod
    def from_env_or_none(cls) -> "SkylinkConfig | None":
        """Return None (instead of raising) when no key is configured.

        Used by scheduled runs so a missing key is a graceful skip.
        """
        if not os.getenv("SKYLINK_RAPIDAPI_KEY", "").strip():
            return None
        return cls.from_env()

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)
