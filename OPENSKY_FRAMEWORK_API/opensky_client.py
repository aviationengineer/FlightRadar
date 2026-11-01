"""Class-based client for the OpenSky Network API.

Full docs: https://openskynetwork.github.io/opensky-api/ (v1.4.0)
Landing:   https://opensky-network.org/data/api
Base:      https://opensky-network.org/api

Auth is OAuth2 client-credentials only (basic auth no longer accepted).
Create an API client on your OpenSky account page for client_id/secret.
Token endpoint: POST https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token
Tokens expire after 30 minutes; 401 means refresh and retry.

Rate limits (credits per day, per endpoint bucket):
- Anonymous: 400/day. Authenticated standard: 4,000/day.
- /states/all cost by bbox area: ≤25 sq° = 1, 25–100 = 2, 100–400 = 3, >400 or global = 4.
- Anonymous: time param ignored, 10s resolution. Authenticated: up to 1h old, 5s resolution.
"""

from __future__ import annotations

import time
from typing import Any
import requests

from .config import OpenSkyConfig
from .models import OpenSkyState

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
        # Docs: tokens expire after 30 minutes
        self._token_expiry = time.time() + int(data.get("expires_in", 1800))
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        token = self._get_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    # ------------------------------------------------------------------
    # states
    # ------------------------------------------------------------------
    def get_states(
        self,
        lamin: float | None = None,
        lomin: float | None = None,
        lamax: float | None = None,
        lomax: float | None = None,
        icao24: str | None = None,
        time: int | None = None,
        extended: bool = False,
    ) -> tuple[int, list[OpenSkyState]]:
        """GET /states/all – current state vectors. Returns (time, states).

        Params: time (unix, authenticated only, ≤1h old), icao24 (repeatable),
        bbox lamin/lomin/lamax/lomax, extended=1 to request aircraft category.
        """
        params: dict[str, Any] = {}
        if lamin is not None:
            params.update(lamin=lamin, lomin=lomin, lamax=lamax, lomax=lomax)
        if icao24:
            params["icao24"] = icao24
        if time is not None:
            params["time"] = time
        if extended:
            params["extended"] = 1
        data = self.http.get("/states/all", params=params, headers=self._auth_headers())
        states = [OpenSkyState.from_vector(v) for v in (data.get("states") or [])]
        return int(data.get("time", 0)), states

    def get_states_own(
        self,
        time: int | None = None,
        icao24: str | None = None,
        serials: str | None = None,
    ) -> tuple[int, list[OpenSkyState]]:
        """GET /states/own – your sensors only. No credit cost, auth required."""
        params: dict[str, Any] = {}
        if time is not None:
            params["time"] = time
        if icao24:
            params["icao24"] = icao24
        if serials:
            params["serials"] = serials
        data = self.http.get("/states/own", params=params, headers=self._auth_headers())
        states = [OpenSkyState.from_vector(v) for v in (data.get("states") or [])]
        return int(data.get("time", 0)), states

    # ------------------------------------------------------------------
    # flights – responses are JSON arrays (not wrapped)
    # ------------------------------------------------------------------
    @staticmethod
    def _as_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("flights", "data", "result"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    def get_flights_all(self, begin: int, end: int) -> list[dict[str, Any]]:
        """GET /flights/all – flights in [begin, end]. Interval ≤ 2 hours.

        404 with empty body if none found.
        """
        data = self.http.get("/flights/all", params={"begin": begin, "end": end}, headers=self._auth_headers())
        return self._as_list(data)

    def get_flights_aircraft(self, icao24: str, begin: int, end: int) -> list[dict[str, Any]]:
        """GET /flights/aircraft – flights for one aircraft. Interval ≤ 2 days.

        Nightly batch: previous-day or earlier flights only.
        """
        data = self.http.get(
            "/flights/aircraft",
            params={"icao24": icao24.lower(), "begin": begin, "end": end},
            headers=self._auth_headers(),
        )
        return self._as_list(data)

    def get_flights_arrival(self, airport: str, begin: int, end: int) -> list[dict[str, Any]]:
        """GET /flights/arrival – arrivals at airport (ICAO, e.g. EDDF). Interval ≤ 2 days."""
        data = self.http.get(
            "/flights/arrival",
            params={"airport": airport.upper(), "begin": begin, "end": end},
            headers=self._auth_headers(),
        )
        return self._as_list(data)

    def get_flights_departure(self, airport: str, begin: int, end: int) -> list[dict[str, Any]]:
        """GET /flights/departure – departures from airport (ICAO)."""
        data = self.http.get(
            "/flights/departure",
            params={"airport": airport.upper(), "begin": begin, "end": end},
            headers=self._auth_headers(),
        )
        return self._as_list(data)

    # ------------------------------------------------------------------
    # tracks
    # ------------------------------------------------------------------
    def get_tracks(self, icao24: str, time: int = 0) -> dict[str, Any]:
        """GET /tracks/all – trajectory for aircraft.

        time=0 gives the live track if any. Tracks >30 days old unavailable.
        Response: {icao24, startTime, endTime, callsign, path: [[time, lat, lon, baro_alt, track, on_ground], ...]}
        """
        return self.http.get("/tracks/all", params={"icao24": icao24.lower(), "time": time}, headers=self._auth_headers())
