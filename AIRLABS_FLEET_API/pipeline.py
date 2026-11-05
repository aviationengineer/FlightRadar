"""Orchestration: AirLabs /fleets -> transform -> Google Sheets.

Run modes
---------
- ``run_full_refresh`` — monthly: paginated pull of the whole fleet DB,
  full replace of AIRLABS_Fleets, plus quality + log + catalog rows.
- ``run_weekly_refresh`` — weekly: rotating slice of the top-airline list
  (``weekly_slice_size`` airlines per week, ISO-week rotation), merged
  into the existing sheet contents by hex/reg key.
- ``run_airline_refresh`` — one airline, merged the same way.

Quota discipline (free tier: 1,000 requests/month)
--------------------------------------------------
- Disk cache is MANDATORY: full pulls cached 28 days, per-airline pulls
  7 days, airline names 30 days. A cache hit costs zero requests.
- ``QuotaTracker`` persists month-to-date request counts in
  ``data/state/quota.json``; the pipeline refuses to start a pull once
  the monthly soft cap (default 900) is reached.
- Projected budget (see README for the full table): full pull ~600
  requests (MEASURE on the first live run — the real fleet size is
  unknown until then) + weekly ~40/week (~160/month) + names ~25 once
  (then cached) = ~785/month, ~215 headroom under the 1,000 limit.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.expanduser("~/workspace"))

from LIB.logging_utils import get_logger  # noqa: E402

from .airlabs_client import AirlabsClient, AirlabsRateLimitError  # noqa: E402
from .config import (  # noqa: E402
    TAB_CATALOG, TAB_FLEETS, TAB_LOG, TAB_QUALITY,
    AirlabsConfig, FULL_PULL_REQUEST_ESTIMATE,
)
from .models import FleetAircraft  # noqa: E402
from .sheets_sink import AirlabsSheetsSink  # noqa: E402
from .transforms import (  # noqa: E402
    aircraft_to_rows, compute_quality_metrics, dedupe_by_hex,
    enrich_airline_names, merge_fleets, normalize_aircraft,
    quality_metrics_to_rows, rows_to_aircraft,
)

log = get_logger("airlabs-fleet")

LOG_HEADERS = ["run_timestamp_utc", "run_type", "status", "aircraft_fetched",
               "aircraft_written", "requests_made", "cache_hit",
               "duration_seconds", "error"]
QUALITY_HEADERS = ["metric", "value", "checked_at_utc"]
CATALOG_HEADERS = ["source", "endpoint", "coverage", "refresh_cadence",
                   "quota_budget", "last_run", "status"]


# ----------------------------------------------------------------------
# disk cache (mandatory — the free tier only allows 1,000 req/month)
# ----------------------------------------------------------------------
class DiskCache:
    """Tiny JSON file cache with TTL. Keys are file names."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str, ttl_seconds: int) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (ValueError, OSError):
            return None
        fetched_at = payload.get("fetched_at")
        if not fetched_at:
            return None
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(fetched_at)).total_seconds()
        except ValueError:
            return None
        if age > ttl_seconds:
            return None
        return payload.get("data")

    def put(self, key: str, data: Any) -> None:
        path = self._path(key)
        path.write_text(json.dumps({
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }))


class QuotaTracker:
    """Month-to-date AirLabs request counts, persisted in a JSON file."""

    def __init__(self, state_dir: Path, soft_cap: int):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / "quota.json"
        self.soft_cap = soft_cap

    def _month(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except (ValueError, OSError):
            return {"month": self._month(), "requests": 0}
        if data.get("month") != self._month():
            return {"month": self._month(), "requests": 0}
        return data

    def used(self) -> int:
        return int(self.load().get("requests", 0))

    def add(self, count: int) -> int:
        data = self.load()
        data["requests"] = int(data.get("requests", 0)) + count
        data["month"] = self._month()
        self.path.write_text(json.dumps(data))
        return data["requests"]

    def can_spend(self, estimate: int) -> bool:
        return self.used() + estimate <= self.soft_cap


@dataclass
class IngestionResult:
    run_type: str = ""
    status: str = "ok"
    fetched: int = 0
    deduped: int = 0
    written: int = 0
    requests_made: int = 0
    cache_hit: bool = False
    duration_seconds: float = 0.0
    spreadsheet_id: str = ""
    errors: list[str] = field(default_factory=list)


class AirlabsFleetPipeline:
    """High-level pipeline for AirLabs fleet ingestion."""

    def __init__(self, config: AirlabsConfig | None = None,
                 client: AirlabsClient | None = None,
                 sink: AirlabsSheetsSink | None = None):
        self.config = config or AirlabsConfig.from_env()
        self.client = client or AirlabsClient(self.config)
        self.sink = sink or AirlabsSheetsSink(
            spreadsheet_id=self.config.spreadsheet_id)
        self.cache = DiskCache(self.config.cache_dir)
        self.quota = QuotaTracker(self.config.state_dir,
                                  self.config.monthly_soft_cap)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _airline_names(self) -> dict[str, str]:
        """IATA/ICAO -> name map, from 30-day disk cache or /airlines."""
        cached = self.cache.get(
            "airline_names",
            self.config.airline_names_ttl_days * 86400)
        if isinstance(cached, dict):
            return cached
        try:
            before = self.client.request_count
            names = self.client.get_airline_names()
            self.quota.add(self.client.request_count - before)
            self.cache.put("airline_names", names)
            return names
        except Exception as exc:  # enrichment is best-effort, never fatal
            log.warning("Airline-name enrichment failed (%s); names left blank", exc)
            return {}

    def _weekly_slice(self) -> list[str]:
        """Rotating slice of the top-airline list for this ISO week."""
        airlines = self.config.top_airlines
        if not airlines:
            return []
        size = max(1, self.config.weekly_slice_size)
        week = datetime.now(timezone.utc).isocalendar()[1]
        start = (week * size) % len(airlines)
        return [airlines[(start + i) % len(airlines)] for i in range(size)]

    def _fetch_full(self) -> tuple[list[FleetAircraft], bool, int]:
        """Full fleet pull (cache-first). Returns (aircraft, cache_hit, reqs)."""
        cached = self.cache.get(
            "fleets_full", self.config.full_cache_ttl_days * 86400)
        if isinstance(cached, list):
            log.info("Full-pull cache hit (%d aircraft, 0 requests)", len(cached))
            return [FleetAircraft(**rec) for rec in cached], True, 0
        before = self.client.request_count
        aircraft = self.client.get_all_fleets()
        made = self.client.request_count - before
        self.quota.add(made)
        self.cache.put("fleets_full", [a.to_dict() for a in aircraft])
        return aircraft, False, made

    def _fetch_airline(self, iata: str) -> tuple[list[FleetAircraft], bool, int]:
        """One airline's fleet (cache-first). Returns (aircraft, hit, reqs)."""
        key = f"fleets_airline_{iata.upper()}"
        cached = self.cache.get(key, self.config.airline_cache_ttl_days * 86400)
        if isinstance(cached, list):
            return [FleetAircraft(**rec) for rec in cached], True, 0
        before = self.client.request_count
        aircraft = self.client.get_airline_fleets(iata=iata)
        made = self.client.request_count - before
        self.quota.add(made)
        self.cache.put(key, [a.to_dict() for a in aircraft])
        return aircraft, False, made

    def _write_outputs(self, aircraft: list[FleetAircraft], result: IngestionResult,
                       run_type: str, replace_fleets: bool = True) -> None:
        """Write fleets + quality + log + catalog tabs."""
        result.written = self.sink.write_table(
            TAB_FLEETS, FleetAircraft.sheet_headers(),
            aircraft_to_rows(aircraft), replace=replace_fleets)
        metrics = compute_quality_metrics(
            aircraft, duplicates_removed=result.fetched - result.deduped)
        self.sink.write_table(TAB_QUALITY, QUALITY_HEADERS,
                              quality_metrics_to_rows(metrics), replace=True)
        self.sink.append_rows(TAB_LOG, [self._log_row(result, run_type)],
                              headers=LOG_HEADERS)
        self.sink.write_table(TAB_CATALOG, CATALOG_HEADERS,
                              [self._catalog_row(result)], replace=True)

    def _log_row(self, result: IngestionResult, run_type: str) -> list[Any]:
        return [self._now_iso(), run_type, result.status, result.fetched,
                result.written, result.requests_made, str(result.cache_hit),
                round(result.duration_seconds, 1),
                "; ".join(result.errors)[:500]]

    def _catalog_row(self, result: IngestionResult) -> list[Any]:
        return ["AirLabs", "/fleets (GET)",
                "Global airline fleets, per-aircraft (hex, reg, type, model, age)",
                "Monthly full pull + weekly top-airline refresh",
                f"<= {self.config.monthly_soft_cap} / 1,000 req/month (free tier, soft cap)",
                self._now_iso(), result.status]

    def _finalise(self, result: IngestionResult, aircraft: list[FleetAircraft],
                  run_type: str, started: float) -> IngestionResult:
        result.duration_seconds = time.monotonic() - started
        result.deduped = len(aircraft)
        result.spreadsheet_id = self.sink.spreadsheet_id or ""
        return result

    def _prepare(self, aircraft: list[FleetAircraft],
                 names: dict[str, str]) -> list[FleetAircraft]:
        aircraft = normalize_aircraft(aircraft)
        aircraft = enrich_airline_names(aircraft, names)
        return dedupe_by_hex(aircraft)

    # ------------------------------------------------------------------
    # run modes
    # ------------------------------------------------------------------
    def run_full_refresh(self, write: bool = True) -> IngestionResult:
        """Monthly full fleet pull."""
        started = time.monotonic()
        result = IngestionResult(run_type="full")
        try:
            if not self.quota.can_spend(FULL_PULL_REQUEST_ESTIMATE):
                result.status = "skipped_quota"
                result.errors.append(
                    f"Monthly soft cap reached: {self.quota.used()}/"
                    f"{self.config.monthly_soft_cap} requests used; "
                    f"full pull (~{FULL_PULL_REQUEST_ESTIMATE} reqs) skipped.")
                log.warning(result.errors[0])
                return self._finalise(result, [], "full", started)
            aircraft, hit, made = self._fetch_full()
            result.cache_hit = hit
            result.requests_made = made
            result.fetched = len(aircraft)
            aircraft = self._prepare(aircraft, self._airline_names())
            result.deduped = len(aircraft)
            if write:
                self._write_outputs(aircraft, result, "full")
            else:
                result.written = len(aircraft)
            result.status = "ok"
        except AirlabsRateLimitError as exc:
            result.status = "rate_limited"
            result.errors.append(f"{exc} (limit={exc.limit_kind})")
            log.error("Full refresh rate-limited: %s", exc)
        except Exception as exc:
            result.status = "error"
            result.errors.append(str(exc))
            log.error("Full refresh failed: %s", exc)
        return self._finalise(result, aircraft if 'aircraft' in dir() else [], "full", started)

    def run_weekly_refresh(self, write: bool = True) -> IngestionResult:
        """Weekly refresh of the rotating top-airline slice, merged in."""
        started = time.monotonic()
        result = IngestionResult(run_type="weekly")
        aircraft: list[FleetAircraft] = []
        try:
            airlines = self._weekly_slice()
            log.info("Weekly refresh slice: %s", ",".join(airlines))
            fetched: list[FleetAircraft] = []
            cache_hits = 0
            for iata in airlines:
                batch, hit, made = self._fetch_airline(iata)
                fetched.extend(batch)
                result.requests_made += made
                cache_hits += 1 if hit else 0
            result.cache_hit = cache_hits == len(airlines) and bool(airlines)
            result.fetched = len(fetched)
            fresh = self._prepare(fetched, self._airline_names())
            if write:
                existing = rows_to_aircraft(self.sink.read_table(TAB_FLEETS))
                aircraft = merge_fleets(existing, fresh)
                result.deduped = len(aircraft)
                self._write_outputs(aircraft, result, "weekly")
            else:
                aircraft = fresh
                result.written = len(aircraft)
            result.status = "ok"
        except AirlabsRateLimitError as exc:
            result.status = "rate_limited"
            result.errors.append(f"{exc} (limit={exc.limit_kind})")
            log.error("Weekly refresh rate-limited: %s", exc)
        except Exception as exc:
            result.status = "error"
            result.errors.append(str(exc))
            log.error("Weekly refresh failed: %s", exc)
        return self._finalise(result, aircraft, "weekly", started)

    def run_airline_refresh(self, iata: str, write: bool = True) -> IngestionResult:
        """Refresh a single airline's fleet, merged into the sheet."""
        started = time.monotonic()
        result = IngestionResult(run_type=f"airline:{iata.upper()}")
        aircraft: list[FleetAircraft] = []
        try:
            fresh_raw, hit, made = self._fetch_airline(iata)
            result.cache_hit = hit
            result.requests_made = made
            result.fetched = len(fresh_raw)
            fresh = self._prepare(fresh_raw, self._airline_names())
            if write:
                existing = rows_to_aircraft(self.sink.read_table(TAB_FLEETS))
                aircraft = merge_fleets(existing, fresh)
                result.deduped = len(aircraft)
                self._write_outputs(aircraft, result, result.run_type)
            else:
                aircraft = fresh
                result.written = len(aircraft)
            result.status = "ok"
        except AirlabsRateLimitError as exc:
            result.status = "rate_limited"
            result.errors.append(f"{exc} (limit={exc.limit_kind})")
            log.error("Airline refresh rate-limited: %s", exc)
        except Exception as exc:
            result.status = "error"
            result.errors.append(str(exc))
            log.error("Airline refresh failed: %s", exc)
        return self._finalise(result, aircraft, result.run_type, started)
