"""Domain models for Airline Fleet Monitor data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class AirlineFleet:
    """Normalised per-airline fleet snapshot.

    This is an ACTIVE-fleet picture derived from ADS-B observation, NOT a
    registered-fleet roster: an airframe counts as active when observed in
    flight telemetry within the last 7 days, idle when unobserved 8-30 days,
    stored when unobserved 30+ days (or at a storage airpark).
    """

    airline: str = ""
    iata: str = ""
    icao: str = ""
    country: str = ""
    active: int = 0
    idle_7_29d: int = 0
    stored_30d_plus: int = 0
    total: int = 0
    average_age: Optional[float] = None
    coverage_confidence: str = ""
    slug: str = ""
    status: str = ""
    hubs: str = ""  # comma-joined ICAO hub codes
    fetched_at: str = ""

    @classmethod
    def from_export_dict(cls, data: dict[str, Any], fetched_at: str = "") -> "AirlineFleet":
        """Create from one record of /data/airlines.json (bulk export)."""
        active = _to_int(data.get("active_count"))
        idle = _to_int(data.get("idle_count"))
        stored = _to_int(data.get("stored_count"))
        total = _to_int_or_none(data.get("observed_fleet_count"))
        if total is None:
            total = active + idle + stored
        hubs = data.get("hubs") or []
        if isinstance(hubs, str):
            hubs = [hubs]
        return cls(
            airline=str(data.get("name") or ""),
            iata=str(data.get("iata") or ""),
            icao=str(data.get("icao") or ""),
            country=str(data.get("country") or ""),
            active=active,
            idle_7_29d=idle,
            stored_30d_plus=stored,
            total=total,
            average_age=_to_float(data.get("avg_age")),
            coverage_confidence=str(data.get("coverage_confidence") or ""),
            slug=str(data.get("slug") or ""),
            status=str(data.get("status") or ""),
            hubs=",".join(str(h) for h in hubs if h),
            fetched_at=fetched_at,
        )

    @classmethod
    def from_api_dict(cls, data: dict[str, Any], fetched_at: str = "") -> "AirlineFleet":
        """Create from one /api/v1/airlines/{slug} response.

        Accepts either the bare airline dict or the {"success": true,
        "data": {...}} envelope. Note: the per-airline endpoint currently
        returns avg_age=null where the bulk export carries a value, so the
        export is the richer source; this method is for spot checks.
        """
        if isinstance(data.get("data"), dict):
            data = data["data"]
        hubs = data.get("hubs") or []
        if isinstance(hubs, str):
            try:
                import json as _json

                hubs = _json.loads(hubs)
            except ValueError:
                hubs = [hubs]
        if not isinstance(hubs, list):
            hubs = []
        return cls.from_export_dict(
            {
                "name": data.get("name"),
                "iata": data.get("iata"),
                "icao": data.get("icao"),
                "country": data.get("country"),
                "active_count": data.get("active_count"),
                "idle_count": data.get("idle_count"),
                "stored_count": data.get("stored_count"),
                "observed_fleet_count": data.get("observed_fleet_count"),
                "avg_age": data.get("avg_age"),
                "coverage_confidence": data.get("coverage_confidence"),
                "slug": data.get("slug"),
                "status": data.get("status"),
                "hubs": hubs,
            },
            fetched_at=fetched_at,
        )

    def to_sheet_row(self) -> list[Any]:
        return [
            self.airline,
            self.iata,
            self.icao,
            self.country,
            self.active,
            self.idle_7_29d,
            self.stored_30d_plus,
            self.total,
            self.average_age,
            self.coverage_confidence,
            self.slug,
            self.hubs,
            self.fetched_at,
        ]

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "airline",
            "iata",
            "icao",
            "country",
            "active",
            "idle_7_29d",
            "stored_30d_plus",
            "total",
            "average_age",
            "coverage_confidence",
            "slug",
            "hubs",
            "fetched_at",
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DataQualityRow:
    """One data-quality check result, written to AFM_Data_Quality."""

    check: str = ""
    result: str = ""  # PASS / WARN / FAIL
    detail: str = ""
    value: str = ""
    fetched_at: str = ""

    def to_sheet_row(self) -> list[Any]:
        return [self.check, self.result, self.detail, self.value, self.fetched_at]

    @staticmethod
    def sheet_headers() -> list[str]:
        return ["check", "result", "detail", "value", "fetched_at"]


@dataclass
class IngestionLogRow:
    """One ingestion run summary, written to AFM_Ingestion_Log."""

    run_at: str = ""
    source: str = ""
    records_fetched: int = 0
    airlines_written: int = 0
    total_airframes: int = 0
    status: str = ""  # OK / PARTIAL / FAILED
    notes: str = ""

    def to_sheet_row(self) -> list[Any]:
        return [
            self.run_at,
            self.source,
            self.records_fetched,
            self.airlines_written,
            self.total_airframes,
            self.status,
            self.notes,
        ]

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "run_at",
            "source",
            "records_fetched",
            "airlines_written",
            "total_airframes",
            "status",
            "notes",
        ]


def _to_int(v: Any) -> int:
    result = _to_int_or_none(v)
    return result if result is not None else 0


def _to_int_or_none(v: Any) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
