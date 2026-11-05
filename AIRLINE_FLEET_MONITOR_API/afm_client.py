"""Class-based client for the Airline Fleet Monitor public API + export hub.

Verified live 2026-11-05 (see docs/ARCHITECTURE.md):
- Base API: https://airlinefleetmonitor.com/api/v1  (Cloudflare Workers)
- OpenAPI contract: https://airlinefleetmonitor.com/openapi.json
- Bulk export: https://airlinefleetmonitor.com/data/airlines.json
- Auth: NONE required — no key, no account, no bearer token. The OpenAPI
  document declares no security schemes and all endpoints return 200
  unauthenticated. Licence: ODbL (Open Data Commons Open Database License).

Environment lesson (do not rediscover): this sandbox's proxy env contains
bracketed IPv6 no_proxy entries that break trust_env parsing in httpx, and
TLS needs the egress CA bundle. This client therefore uses requests with
trust_env disabled, explicit proxies from the environment, and
SSL_CERT_FILE as the CA bundle — the same pattern the sibling frameworks
use for httpx, adapted for requests.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from .config import AFMConfig
from .models import AirlineFleet


class AFMAPIError(Exception):
    """Raised for API-level failures."""

    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def build_session(user_agent: str) -> requests.Session:
    """requests session with explicit proxy + CA bundle (no trust_env).

    trust_env is disabled so the bracketed-IPv6 no_proxy entries in this
    sandbox cannot break proxy parsing; proxies are passed explicitly.
    """
    session = requests.Session()
    session.trust_env = False
    proxies: dict[str, str] = {}
    for key in ("https_proxy", "http_proxy", "HTTPS_PROXY", "HTTP_PROXY"):
        if os.environ.get(key):
            scheme = "https" if key.lower().startswith("https") else "http"
            proxies.setdefault(scheme, os.environ[key])
    if proxies:
        session.proxies.update(proxies)
    session.verify = os.environ.get("SSL_CERT_FILE") or True
    session.headers.update(
        {"Accept": "application/json", "User-Agent": user_agent}
    )
    return session


class AirlineFleetMonitorClient:
    """Thin, class-based wrapper around the AFM public API + export hub."""

    # Bulk export endpoints (Data Export Hub)
    EXPORT_AIRLINES = "/data/airlines.json"
    EXPORT_AIRCRAFT_TYPES = "/data/aircraft_types.json"
    EXPORT_AIRFRAMES = "/data/airframes.json"
    EXPORT_ROUTES = "/data/routes.json"
    EXPORT_LESSORS = "/data/lessors.json"

    def __init__(self, config: AFMConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or build_session(config.user_agent)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _get_json(self, url: str) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                resp = self.session.get(url, timeout=self.config.timeout_seconds)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.config.max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise AFMAPIError(f"Network error calling {url}: {exc}") from exc
            if resp.status_code == 429:
                if attempt < self.config.max_retries - 1:
                    time.sleep(int(resp.headers.get("Retry-After", "5")))
                    continue
                raise AFMAPIError("429 Rate limited – back off and retry.",
                                  status_code=429, payload=_safe_json(resp))
            if resp.status_code == 401:
                raise AFMAPIError(
                    "401 Unauthorized – the endpoint unexpectedly requires auth.",
                    status_code=401, payload=_safe_json(resp))
            if resp.status_code == 403:
                raise AFMAPIError("403 Forbidden – access denied.",
                                  status_code=403, payload=_safe_json(resp))
            if resp.status_code == 404:
                raise AFMAPIError(f"404 Not found: {url}",
                                  status_code=404, payload=_safe_json(resp))
            if resp.status_code >= 400:
                raise AFMAPIError(
                    f"API error {resp.status_code} on {url}: {resp.text[:500]}",
                    status_code=resp.status_code, payload=_safe_json(resp))
            return _safe_json(resp)
        raise AFMAPIError(f"Failed after {self.config.max_retries} attempts: {last_exc}")

    # ------------------------------------------------------------------
    # bulk export (PRIMARY source — one request, whole directory)
    # ------------------------------------------------------------------
    def get_airlines_export(self) -> list[dict[str, Any]]:
        """Download the complete airlines directory JSON (~1.1 MB, 2,500 rows).

        Returns the raw list: 860 active + 1,640 defunct carriers, each with
        observed/active/idle/stored counts, average age and hubs.
        """
        data = self._get_json(self.config.export_url)
        if not isinstance(data, list):
            raise AFMAPIError(
                f"Unexpected export shape: expected a JSON list, got {type(data).__name__}",
                payload=data if isinstance(data, dict) else None,
            )
        return data

    def get_airlines_export_fleets(self, fetched_at: str = "") -> list[AirlineFleet]:
        """Bulk export parsed into AirlineFleet models (all statuses)."""
        return [AirlineFleet.from_export_dict(r, fetched_at=fetched_at)
                for r in self.get_airlines_export()]

    # ------------------------------------------------------------------
    # per-entity API (verification / spot checks)
    # ------------------------------------------------------------------
    def get_airline(self, slug: str) -> AirlineFleet:
        """GET /api/v1/airlines/{slug} — one airline profile + fleet counts."""
        payload = self._get_json(f"{self.config.api_base_url}/airlines/{slug}")
        if not isinstance(payload, dict) or not payload.get("success", True):
            raise AFMAPIError(f"Unexpected airline payload for {slug!r}",
                              payload=payload)
        data = payload.get("data") or payload
        return AirlineFleet.from_api_dict(data)

    def get_aircraft_type(self, slug: str) -> dict[str, Any]:
        """GET /api/v1/aircraft/{slug} — type specs + observed fleet counts."""
        payload = self._get_json(f"{self.config.api_base_url}/aircraft/{slug}")
        if isinstance(payload, dict):
            return payload.get("data") or payload
        return {"_raw": payload}

    def get_airframe(self, tail_or_hex: str) -> dict[str, Any]:
        """GET /api/v1/airframes/{tail} — airframe by registration or Mode S hex."""
        payload = self._get_json(f"{self.config.api_base_url}/airframes/{tail_or_hex}")
        if isinstance(payload, dict):
            return payload.get("data") or payload
        return {"_raw": payload}

    def get_lessor(self, slug: str) -> dict[str, Any]:
        """GET /api/v1/lessors/{slug} — lessor managed portfolio."""
        payload = self._get_json(f"{self.config.api_base_url}/lessors/{slug}")
        if isinstance(payload, dict):
            return payload.get("data") or payload
        return {"_raw": payload}

    def get_deliveries(self) -> dict[str, Any]:
        """GET /api/v1/deliveries — recent deliveries (documented on /api-docs/,
        not listed in openapi.json; verified 200 live 2026-11-05)."""
        payload = self._get_json(f"{self.config.api_base_url}/deliveries")
        if isinstance(payload, dict):
            return payload.get("data") or payload
        return {"_raw": payload}

    def get_openapi(self) -> dict[str, Any]:
        """GET /openapi.json — the published OpenAPI 3.0 contract."""
        payload = self._get_json(f"{self.config.base_url}/openapi.json")
        if not isinstance(payload, dict):
            raise AFMAPIError("Unexpected openapi.json shape", payload=payload)
        return payload


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"_raw": resp.text[:2000]}
