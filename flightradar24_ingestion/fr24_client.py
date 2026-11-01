"""Class-based client for the FlightRadar24 API.

Docs: https://fr24api.flightradar24.com/docs
Blog:  https://www.flightradar24.com/blog/b2b/flightradar24-api/

Auth:  Authorization: Bearer <token>, API-Version: v1
Base:  https://fr24api.flightradar24.com
"""

from __future__ import annotations

from typing import Any
import requests

from .config import FR24Config
from .models import Flight


class FR24APIError(Exception):
    """Raised for API-level failures."""

    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class FlightRadar24Client:
    """Thin, class-based wrapper around the FR24 REST API v1."""

    def __init__(self, config: FR24Config, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_token}",
            "API-Version": self.config.api_version,
            "Accept": "application/json",
            "User-Agent": "goaviator-fr24-ingestion/1.0",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        try:
            resp = self.session.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise FR24APIError(f"Network error calling {path}: {exc}") from exc

        if resp.status_code == 401:
            raise FR24APIError(
                "401 Unauthorized – check your API token (Key management page).",
                status_code=401,
                payload=_safe_json(resp),
            )
        if resp.status_code == 402:
            raise FR24APIError(
                "402 Insufficient credits – top up or check subscription.",
                status_code=402,
                payload=_safe_json(resp),
            )
        if resp.status_code == 429:
            raise FR24APIError(
                "429 Rate limited – back off and retry.",
                status_code=429,
                payload=_safe_json(resp),
            )
        if resp.status_code >= 400:
            raise FR24APIError(
                f"API error {resp.status_code} on {path}: {resp.text[:500]}",
                status_code=resp.status_code,
                payload=_safe_json(resp),
            )

        data = _safe_json(resp)
        if not isinstance(data, dict):
            raise FR24APIError(f"Unexpected non-dict response from {path}", payload=data)
        return data

    @staticmethod
    def _extract_flight_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Handle the few envelope shapes FR24 uses (data / result / flights)."""
        for key in ("data", "result", "flights", "positions"):
            val = payload.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                # sometimes nested: {"data": [...]} inside "result"
                for inner in ("data", "flights", "positions"):
                    if isinstance(val.get(inner), list):
                        return val[inner]
        # Fallback: if payload itself looks like a single flight dict
        if any(k in payload for k in ("fr24_id", "callsign", "flight", "reg")):
            return [payload]
        return []

    # ------------------------------------------------------------------
    # live endpoints
    # ------------------------------------------------------------------
    def get_live_positions_light(
        self,
        bounds: str,
        limit: int | None = None,
    ) -> list[Flight]:
        """Live positions (light) within a bounding box.

        Args:
            bounds: "N,S,W,E" e.g. "50.682,46.218,14.422,22.243"
            limit: optional client-side cap on number of flights returned
        """
        params: dict[str, Any] = {"bounds": bounds}
        payload = self._get("/api/live/flight-positions/light", params=params)
        raw = self._extract_flight_list(payload)
        flights = [Flight.from_api_dict(r) for r in raw]
        return flights[:limit] if limit else flights

    def get_live_positions_full(
        self,
        bounds: str,
        limit: int | None = None,
    ) -> list[Flight]:
        """Live positions (full) within a bounding box – richer detail, more credits."""
        params: dict[str, Any] = {"bounds": bounds}
        payload = self._get("/api/live/flight-positions/full", params=params)
        raw = self._extract_flight_list(payload)
        flights = [Flight.from_api_dict(r) for r in raw]
        return flights[:limit] if limit else flights

    def get_live_positions_count(self, bounds: str) -> int:
        payload = self._get("/api/live/flight-positions/count", params={"bounds": bounds})
        for key in ("count", "total", "data"):
            v = payload.get(key)
            if isinstance(v, int):
                return v
        return 0

    # ------------------------------------------------------------------
    # static data
    # ------------------------------------------------------------------
    def get_airport_full(self, code: str) -> dict[str, Any]:
        """Detailed airport info by IATA or ICAO code."""
        return self._get(f"/api/static/airports/{code}/full")

    def get_airline_light(self, icao: str) -> dict[str, Any]:
        """Basic airline info by ICAO code."""
        return self._get(f"/api/static/airlines/{icao}/light")

    # ------------------------------------------------------------------
    # flight summary / tracks / historic
    # ------------------------------------------------------------------
    def get_flight_tracks(self, flight_id: str) -> dict[str, Any]:
        return self._get("/api/flight-tracks", params={"flight_id": flight_id})

    def get_historic_positions_light(
        self,
        bounds: str,
        timestamp: str,
    ) -> list[Flight]:
        """Historical snapshot. timestamp: ISO-8601, back to 2016-05-11 per plan."""
        payload = self._get(
            "/api/historic/flight-positions/light",
            params={"bounds": bounds, "timestamp": timestamp},
        )
        return [Flight.from_api_dict(r) for r in self._extract_flight_list(payload)]

    def get_usage(self, from_date: str, to_date: str) -> dict[str, Any]:
        """API usage report over a period (YYYY-MM-DD)."""
        return self._get(
            "/api/usage",
            params={"from": from_date, "to": to_date},
        )


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"_raw": resp.text[:2000]}
