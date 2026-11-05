"""Class-based client for the AirLabs API (v9) — fleets endpoint.

Docs: https://airlabs.co/docs/fleets
Base: https://airlabs.co/api/v9
Auth: ``api_key`` query parameter on every call — server-side only.
  The response echoes the key back inside its ``request`` block, so this
  client NEVER logs raw payloads/params and strips that block.

Free tier: 1,000 requests/month, 250/minute, 2,500/hour; ``limit`` max 50
rows/request on free keys. Error codes: minute_limit_exceeded,
hour_limit_exceeded, month_limit_exceeded.

Built on the shared LIB BaseHTTPClient (retries, timeouts, error
mapping) instead of duplicating HTTP logic.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Callable, Optional

import requests

# Allow `from LIB...` when run as a script from the repo root.
sys.path.insert(0, os.path.expanduser("~/workspace"))

from LIB.http import APIError, BaseHTTPClient  # noqa: E402

from .config import AIRLINE_FIELDS, FLEET_FIELDS, AirlabsConfig  # noqa: E402
from .models import FleetAircraft  # noqa: E402


class AirlabsAPIError(APIError):
    """Raised for AirLabs API-level failures."""


class AirlabsRateLimitError(AirlabsAPIError):
    """Raised when AirLabs reports a quota limit.

    Attributes:
        limit_kind: one of "minute", "hour", "month", "unknown".
    """

    def __init__(self, message: str, limit_kind: str = "unknown",
                 status_code: int | None = None, payload: Any = None):
        super().__init__(message, status_code=status_code, payload=payload)
        self.limit_kind = limit_kind


class AirlabsClient(BaseHTTPClient):
    """Thin, class-based wrapper around the AirLabs v9 fleets API."""

    def __init__(self, config: AirlabsConfig,
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] | None = None):
        super().__init__(
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
            session=session,
        )
        self.config = config
        self._sleep = sleep or time.sleep
        self.request_count = 0  # requests made by this client instance

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "goaviator-airlabs-fleet/1.0",
        }

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        # api_key goes in the query string (never in headers, never logged).
        params: dict[str, Any] = {"api_key": self.config.api_key}
        if extra:
            params.update(extra)
        return params

    def _get_page(self, path: str, params: dict[str, Any]) -> Any:
        """One GET, counting the request and mapping AirLabs errors.

        Retries exactly once after ``retry_delay_seconds`` on
        minute_limit_exceeded (if enabled); hour/month limits fail fast.
        The single minute-limit retry lives in ``_paged`` (the error
        arrives inside a 200 payload, so it is detected after the GET).
        """
        self.request_count += 1
        try:
            payload = self.get(path, params=params)
        except APIError as exc:
            # The shared LIB client already retried 429s (up to 3
            # attempts with Retry-After); a surviving 429 is a hard
            # minute-limit signal — fail fast, do not retry again.
            if exc.status_code == 429:
                raise AirlabsRateLimitError(
                    f"429 Rate limited on {path} – back off and retry.",
                    limit_kind="minute", status_code=429, payload=exc.payload,
                ) from exc
            raise AirlabsAPIError(str(exc), status_code=exc.status_code,
                                  payload=exc.payload) from exc
        self._raise_for_error_payload(payload, path)
        return payload

    @staticmethod
    def _raise_for_error_payload(payload: Any, path: str) -> None:
        """AirLabs returns errors inside a 200 payload: {"error": {...}}."""
        if not isinstance(payload, dict):
            return
        err = payload.get("error")
        if not err:
            return
        if isinstance(err, str):
            code, message = err, err
        else:
            code = str(err.get("code") or err.get("message") or "unknown_error")
            message = str(err.get("message") or err)
        kind = "unknown"
        for candidate in ("minute", "hour", "month"):
            if f"{candidate}_limit_exceeded" in code:
                kind = candidate
                break
        if kind == "minute":
            # Minute limits are transient; the caller (_get_page) retries once.
            # Raise a marker the retry loop recognises via limit_kind.
            raise _MinuteLimitExceeded(
                f"AirLabs minute limit exceeded on {path}: {message}", payload=payload
            )
        raise AirlabsRateLimitError(
            f"AirLabs {kind} limit exceeded on {path}: {message} "
            f"(code={code})",
            limit_kind=kind, payload=payload,
        )

    @staticmethod
    def _extract_records(payload: Any) -> list[dict[str, Any]]:
        """Unwrap the response envelope: {"response": [...]} (or bare list)."""
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict):
            for key in ("response", "data", "fleets", "result"):
                val = payload.get(key)
                if isinstance(val, list):
                    return [r for r in val if isinstance(r, dict)]
                if isinstance(val, dict):
                    for inner in ("data", "fleets"):
                        if isinstance(val.get(inner), list):
                            return [r for r in val[inner] if isinstance(r, dict)]
            if any(k in payload for k in ("hex", "reg_number")):
                return [payload]
        return []

    def _paged(self, path: str, base_params: dict[str, Any],
               max_pages: int | None = None) -> list[dict[str, Any]]:
        """Walk limit/offset pagination until a short page arrives."""
        records: list[dict[str, Any]] = []
        offset = 0
        page = 0
        while True:
            params = dict(base_params)
            params["limit"] = self.config.page_size
            params["offset"] = offset
            try:
                payload = self._get_page(path, params)
            except _MinuteLimitExceeded:
                if self.config.retry_minute_limit:
                    self._sleep(self.config.retry_delay_seconds)
                    payload = self._get_page(path, params)
                else:
                    raise AirlabsRateLimitError(
                        "AirLabs minute limit exceeded.",
                        limit_kind="minute", payload=None,
                    )
            batch = self._extract_records(payload)
            records.extend(batch)
            page += 1
            if len(batch) < self.config.page_size:
                break
            offset += len(batch)
            if max_pages is not None and page >= max_pages:
                break
        return records

    # ------------------------------------------------------------------
    # fleets
    # ------------------------------------------------------------------
    def get_fleets_page(self, limit: int | None = None, offset: int = 0,
                        **filters: Any) -> list[dict[str, Any]]:
        """One page of /fleets (raw dicts). Filters: airline_iata,
        airline_icao, hex, reg_number."""
        params: dict[str, Any] = {"_fields": FLEET_FIELDS}
        params.update({k: v for k, v in filters.items() if v not in (None, "")})
        params["limit"] = limit or self.config.page_size
        params["offset"] = offset
        payload = self._get_page("/fleets", self._params(params))
        return self._extract_records(payload)

    def get_all_fleets(self, max_pages: int | None = None) -> list[FleetAircraft]:
        """Full fleet pull, paginated. Counts requests in request_count."""
        raw = self._paged("/fleets", self._params({"_fields": FLEET_FIELDS}),
                          max_pages=max_pages)
        return [FleetAircraft.from_api_dict(r) for r in raw]

    def get_airline_fleets(self, iata: str | None = None,
                           icao: str | None = None,
                           max_pages: int | None = None) -> list[FleetAircraft]:
        """All aircraft for one airline (by IATA and/or ICAO code)."""
        if not iata and not icao:
            raise ValueError("get_airline_fleets needs iata and/or icao")
        filters: dict[str, Any] = {"_fields": FLEET_FIELDS}
        if iata:
            filters["airline_iata"] = iata.strip().upper()
        if icao:
            filters["airline_icao"] = icao.strip().upper()
        raw = self._paged("/fleets", self._params(filters), max_pages=max_pages)
        return [FleetAircraft.from_api_dict(r) for r in raw]

    # ------------------------------------------------------------------
    # airlines (name enrichment — /fleets has no airline name field)
    # ------------------------------------------------------------------
    def get_airline_names(self, max_pages: int | None = None) -> dict[str, str]:
        """Map IATA and ICAO codes -> airline name, via paginated /airlines.

        Result is cached on disk by the pipeline (30-day TTL), so this
        normally costs zero requests after the first run.
        """
        raw = self._paged("/airlines", self._params({"_fields": AIRLINE_FIELDS}),
                          max_pages=max_pages)
        names: dict[str, str] = {}
        for rec in raw:
            name = str(rec.get("name") or "").strip()
            if not name:
                continue
            for code_key in ("iata_code", "icao_code"):
                code = str(rec.get(code_key) or "").strip().upper()
                if code:
                    names.setdefault(code, name)
        return names


class _MinuteLimitExceeded(AirlabsRateLimitError):
    """Internal marker: minute limit hit inside _get_page's error check."""

    def __init__(self, message: str, payload: Any = None):
        super().__init__(message, limit_kind="minute", payload=payload)
