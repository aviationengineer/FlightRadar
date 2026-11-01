"""Configuration for FlightRadar24 ingestion framework."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FR24Config:
    """Holds FlightRadar24 API configuration.

    Attributes:
        api_token: Bearer token from FR24 API portal → Key management.
        base_url: Base URL, defaults to https://fr24api.flightradar24.com
        api_version: API version header, defaults to v1
        timeout_seconds: HTTP timeout per request
        use_sandbox: If True, hints to use sandbox token/behaviour.
    """

    api_token: str
    base_url: str = "https://fr24api.flightradar24.com"
    api_version: str = "v1"
    timeout_seconds: int = 30
    use_sandbox: bool = False

    @classmethod
    def from_env(cls) -> "FR24Config":
        token = os.getenv("FR24_API_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "FR24_API_TOKEN is not set. "
                "Copy .env.example to .env and add your token from "
                "https://fr24api.flightradar24.com → Key management."
            )
        return cls(
            api_token=token,
            base_url=os.getenv("FR24_BASE_URL", "https://fr24api.flightradar24.com").rstrip("/"),
            api_version=os.getenv("FR24_API_VERSION", "v1"),
            timeout_seconds=int(os.getenv("FR24_TIMEOUT", "30")),
            use_sandbox=os.getenv("FR24_USE_SANDBOX", "false").lower() == "true",
        )
