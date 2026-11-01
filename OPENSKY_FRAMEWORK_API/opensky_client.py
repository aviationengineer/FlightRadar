"""Class-based client for the OpenSky Network API.

Docs: https://opensky-network.org/data/api
Base:  https://opensky-network.org/api

Anonymous usage is rate-limited. OAuth2 client credentials raise limits.
Token endpoint: https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token
"""

from __future__ import annotations

import time
from typing import Any
import requests

from .config import OpenSkyConfig
from .models import OpenSkyState

# Reuse master LIB http client for retry logic
import sys, os
sys.path.insert(0, os.path.expanduser("~/workspace"))
from LIB.http import BaseHTTPClient, APIError


class OpenSkyClient:
    def __init__(self, config: OpenSkyConfig | None = None):
        self.config = config or OpenSkyConfig.from_env()
        self.http = BaseHTTPClient(base_url=self.config.base_url, timeout_seconds=self.config.timeout_seconds)
        self._token: str | None = None
        self._token_expiry: float = 0

    # ------------------------------------------------------------------
    # auth (OAuth2 client credentials, optional)
    # ------------------------------------------------------------------
    def _get_token(self) -> str | None:
        if not self.config.authenticated:
            return None
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        resp = requests.post(
            "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 1800))
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        token = self._get_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------
    def get_states(
        self,
        lamin: float | None = None,
        lomin: float | None = None,
        lamax: float | None = None,
        lomax: float | None = None,
        icao24: str | None = None,
    ) -> tuple[int, list[OpenSkyState]]:
        """GET /states/all – current state vectors.

        Returns (time, states). Bounding box: lamin/lomin/lamax/lomax.
        """
        params: dict[str, Any] = {}
        if lamin is not None:
            params.update(lamin=lamin, lomin=lomin, lamax=lamax, lomax=lomax)
        if icao24:
            params["icao24"] = icao24
        data = self.http.get("/states/all", params=params, headers=self._auth_headers())
        states = [OpenSkyState.from_vector(v) for v in (data.get("states") or [])]
        return int(data.get("time", 0)), states

    def get_flights_all(self, begin: int, end: int) -> list[dict[str, Any]]:
        """GET /flights/all?begin=<unix>&end=<unix> – flights in interval."""
        return self.http.get("/flights/all", params={"begin": begin, "end": end}, headers=self._auth_headers()).get("flights", [])

    def get_tracks(self, icao24: str, time: int = 0) -> dict[str, Any]:
        """GET /tracks/all?icao24=<id>&time=<unix> – track for aircraft."""
        return self.http.get("/tracks/all", params={"icao24": icao24, "time": time}, headers=self._auth_headers())
