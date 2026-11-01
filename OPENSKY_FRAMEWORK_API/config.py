"""Configuration for OpenSky Network ingestion."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenSkyConfig:
    base_url: str = "https://opensky-network.org/api"
    client_id: str = ""
    client_secret: str = ""
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "OpenSkyConfig":
        return cls(
            base_url=os.getenv("OPENSKY_BASE_URL", "https://opensky-network.org/api").rstrip("/"),
            client_id=os.getenv("OPENSKY_CLIENT_ID", "").strip(),
            client_secret=os.getenv("OPENSKY_CLIENT_SECRET", "").strip(),
            timeout_seconds=int(os.getenv("OPENSKY_TIMEOUT", "30")),
        )

    @property
    def authenticated(self) -> bool:
        return bool(self.client_id and self.client_secret)
