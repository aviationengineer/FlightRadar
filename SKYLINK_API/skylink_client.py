"""Class-based client for the Skylink API (via RapidAPI).

Docs: RapidAPI hub — search "Skylink".
Host: skylink-api.p.rapidapi.com (free Basic tier: 1,000 requests/month,
no credit card).

Auth: every request needs
    X-RapidAPI-Key:  <SKYLINK_RAPIDAPI_KEY>
    X-RapidAPI-Host: skylink-api.p.rapidapi.com

Transport reuses the shared LIB (LIB.http.BaseHTTPClient, requests-based),
so the httpx trust_env / bracketed-IPv6 no_proxy problem does not apply.
"""

from __future__ import annotations

import sys
import os
from typing import Any

sys.path.insert(0, os.path.expanduser("~/workspace"))

from LIB.http import APIError, BaseHTTPClient  # noqa: E402

from .config import SkylinkConfig  # noqa: E402
from .models import AircraftObservation, Airline, RegistrationDetail  # noqa: E402


class SkylinkAPIError(APIError):
    """Raised for Skylink API-level failures."""


class SkylinkClient(BaseHTTPClient):
    """Thin, class-based wrapper around the Skylink API (RapidAPI)."""

    def __init__(self, config: SkylinkConfig, session=None):
        super().__init__(
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
            session=session,
        )
        self.config = config
        #: Requests spent so far (ADS-B + registration + airline search).
        self.requests_made: int = 0
        self.adsb_requests: int = 0
        self.registration_lookups: int = 0

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers.update({
            "X-RapidAPI-Key": self.config.api_key,
            "X-RapidAPI-Host": self.config.rapidapi_host,
        })
        return headers

    def _get_counted(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.requests_made += 1
        try:
            return self.get(path, params=params)
        except APIError as exc:
            raise SkylinkAPIError(str(exc), status_code=exc.status_code, payload=exc.payload) from exc

    @staticmethod
    def _extract_list(payload: Any) -> list[dict[str, Any]]:
        """Handle the envelope shapes Skylink/RapidAPI uses."""
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict):
            for key in ("data", "results", "aircraft", "flights", "items"):
                val = payload.get(key)
                if isinstance(val, list):
                    return [r for r in val if isinstance(r, dict)]
                if isinstance(val, dict):
                    for inner in ("data", "results", "aircraft"):
                        if isinstance(val.get(inner), list):
                            return [r for r in val[inner] if isinstance(r, dict)]
            # Single-record payload
            if any(k in payload for k in ("icao24", "callsign", "registration", "reg")):
                return [payload]
        return []

    @staticmethod
    def _next_page(payload: Any, params: dict[str, Any]) -> dict[str, Any] | None:
        """Return params for the next page, or None when paginating is done.

        Supports: explicit `next`/`next_page` URL or token, and simple
        page/per_page incrementing (stop when a page returns fewer rows
        than requested — the caller checks that too).
        """
        if isinstance(payload, dict):
            for key in ("next", "next_page", "nextPage"):
                nxt = payload.get(key)
                if isinstance(nxt, str) and nxt:
                    return {"_next_url": nxt}
                if isinstance(nxt, (int, float)):
                    new = dict(params)
                    new["page"] = int(nxt)
                    return new
            meta = payload.get("meta") or payload.get("pagination") or {}
            if isinstance(meta, dict):
                total = meta.get("total_pages") or meta.get("pages")
                current = meta.get("page") or params.get("page", 1)
                if total is not None and current is not None and int(current) < int(total):
                    new = dict(params)
                    new["page"] = int(current) + 1
                    return new
        # Default: increment the page number.
        new = dict(params)
        new["page"] = int(params.get("page", 1)) + 1
        return new

    # ------------------------------------------------------------------
    # live ADS-B
    # ------------------------------------------------------------------
    def get_adsb_aircraft(
        self,
        airline: str | None = None,
        callsign: str | None = None,
        icao24: str | None = None,
        registration: str | None = None,
        bbox: str | None = None,
        min_altitude: int | None = None,
        max_altitude: int | None = None,
        limit: int | None = None,
    ) -> list[AircraftObservation]:
        """GET /v3/adsb/aircraft — live ADS-B snapshot, paginated.

        Filters (all optional): airline name, callsign, icao24,
        registration, bbox ("minLon,minLat,maxLon,maxLat"), altitude band.
        Follows pages until a short page, an empty page, or
        config.max_pages_per_airline is reached.
        """
        params: dict[str, Any] = {
            "page": 1,
            "per_page": self.config.page_size,
        }
        if airline:
            params["airline"] = airline
        if callsign:
            params["callsign"] = callsign
        if icao24:
            params["icao24"] = icao24
        if registration:
            params["registration"] = registration
        if bbox:
            params["bbox"] = bbox
        if min_altitude is not None:
            params["min_altitude"] = min_altitude
        if max_altitude is not None:
            params["max_altitude"] = max_altitude

        observations: list[AircraftObservation] = []
        pages = 0
        while pages < self.config.max_pages_per_airline:
            self.adsb_requests += 1
            if "_next_url" in params:
                # Full next-page URL: strip base and pass the path through.
                url = params.pop("_next_url")
                path = url.replace(self.config.base_url, "")
                payload = self._get_counted(path)
            else:
                payload = self._get_counted("/v3/adsb/aircraft", params=params)
            raw = self._extract_list(payload)
            observations.extend(AircraftObservation.from_api_dict(r) for r in raw)
            pages += 1
            if limit is not None and len(observations) >= limit:
                return observations[:limit]
            if len(raw) < self.config.page_size:
                break  # short page → last page
            nxt = self._next_page(payload, params)
            if nxt is None:
                break
            params = nxt
        return observations[:limit] if limit else observations

    # ------------------------------------------------------------------
    # aircraft registry
    # ------------------------------------------------------------------
    def get_aircraft_by_registration(self, registration: str) -> RegistrationDetail:
        """GET /v3/aircraft/registration/{reg} — 615k+ aircraft records.

        Use sparingly: only for aircraft whose operator is unresolved
        from the ADS-B record (see pipeline.enrich_unresolved()).
        """
        reg = registration.strip().upper()
        self.registration_lookups += 1
        payload = self._get_counted(f"/v3/aircraft/registration/{reg}")
        if isinstance(payload, dict):
            for key in ("data", "result", "aircraft"):
                val = payload.get(key)
                if isinstance(val, dict):
                    payload = val
                    break
        if not isinstance(payload, dict):
            raise SkylinkAPIError(f"Unexpected response for registration {reg}", payload=payload)
        detail = RegistrationDetail.from_api_dict(payload)
        if not detail.registration:
            detail.registration = reg
        return detail

    # ------------------------------------------------------------------
    # airline search
    # ------------------------------------------------------------------
    def search_airline(self, icao: str | None = None, iata: str | None = None) -> list[Airline]:
        """GET /airlines/search — pass icao OR iata, never both."""
        if icao and iata:
            raise ValueError("search_airline: pass icao OR iata, never both.")
        if not icao and not iata:
            raise ValueError("search_airline: pass icao or iata.")
        params = {"icao": icao} if icao else {"iata": iata}
        payload = self._get_counted("/airlines/search", params=params)
        return [Airline.from_api_dict(r) for r in self._extract_list(payload)]
