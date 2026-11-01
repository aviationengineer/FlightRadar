"""Shared HTTP client with retry and error handling."""

from __future__ import annotations

import time
from typing import Any
import requests


class APIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class BaseHTTPClient:
    """Base HTTP client with retries, timeouts and standard error mapping."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "aviation-framework/1.0",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        merged = {**self._headers(), **(headers or {})}
        last_exc: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                resp = self.session.request(
                    method,
                    url,
                    headers=merged,
                    params=params or {},
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_seconds * (attempt + 1))
                    continue
                raise APIError(f"Network error calling {path}: {exc}") from exc

            if resp.status_code == 429:
                if attempt < self.max_retries - 1:
                    retry_after = int(resp.headers.get("Retry-After", self.backoff_seconds))
                    time.sleep(retry_after)
                    continue
                raise APIError("429 Rate limited", status_code=429, payload=_safe_json(resp))

            if resp.status_code == 401:
                raise APIError("401 Unauthorized – check credentials", status_code=401, payload=_safe_json(resp))
            if resp.status_code == 403:
                raise APIError("403 Forbidden – access denied", status_code=403, payload=_safe_json(resp))
            if resp.status_code >= 400:
                raise APIError(
                    f"API error {resp.status_code} on {path}: {resp.text[:500]}",
                    status_code=resp.status_code,
                    payload=_safe_json(resp),
                )
            return _safe_json(resp)

        raise APIError(f"Failed after {self.max_retries} attempts: {last_exc}")

    def get(self, path: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        return self._request("GET", path, params=params, headers=headers)


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"_raw": resp.text[:2000]}
