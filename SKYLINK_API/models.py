"""Domain models for Skylink API data."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional


def _to_str(v: Any) -> str:
    return "" if v in (None, "") else str(v).strip()


@dataclass
class AircraftObservation:
    """One aircraft observed airborne via live ADS-B.

    Fleet visibility comes from live ADS-B: each airborne aircraft carries
    its airline and aircraft type, so an operator's ACTIVE fleet picture is
    built from what's actually flying — not from a registry of airframes
    that may be stored or retired.
    """

    icao24: str = ""
    registration: str = ""
    callsign: str = ""
    airline_name: str = ""
    airline_icao: str = ""
    aircraft_type: str = ""
    model: str = ""
    manufacturer: str = ""
    operator: str = ""
    observed_at: str = ""

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> "AircraftObservation":
        """Create an observation from a Skylink ADS-B record.

        Defensive: checks several common key names, since RapidAPI
        responses vary slightly between endpoints/versions.
        """
        def _get(*keys: str, default: Any = "") -> Any:
            for k in keys:
                if k in data and data[k] not in (None, ""):
                    return data[k]
            return default

        airline = _get("airline", "operator", default={})
        aircraft = _get("aircraft", default={})

        def _nested(obj: Any, *keys: str) -> str:
            if isinstance(obj, dict):
                for k in keys:
                    if obj.get(k) not in (None, ""):
                        return str(obj[k]).strip()
            return ""

        return cls(
            icao24=_to_str(_get("icao24", "icao", "hex", "icao_hex")),
            registration=_to_str(_get("registration", "reg", "tail_number")),
            callsign=_to_str(_get("callsign", "call_sign", "flight")),
            airline_name=_nested(airline, "name", "airline_name")
                or _to_str(_get("airline_name", "airlineName")),
            airline_icao=_nested(airline, "icao", "icao_code")
                or _to_str(_get("airline_icao", "airlineIcao", "operator_icao")),
            aircraft_type=_nested(aircraft, "type", "aircraft_type", "model")
                or _to_str(_get("aircraft_type", "type", "aircraftType", "model")),
            model=_nested(aircraft, "model")
                or _to_str(_get("model", "aircraft_model")),
            manufacturer=_nested(aircraft, "manufacturer")
                or _to_str(_get("manufacturer")),
            operator=_nested(airline, "name", "operator")
                or _to_str(_get("operator")),
            observed_at=_to_str(_get("observed_at", "timestamp", "time", "last_seen")),
        )

    def to_sheet_row(self) -> list[Any]:
        """Row in the order defined by sheet_headers()."""
        return [
            self.icao24,
            self.registration,
            self.callsign,
            self.airline_name,
            self.airline_icao,
            self.aircraft_type,
            self.model,
            self.manufacturer,
            self.operator,
            self.observed_at,
        ]

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "icao24",
            "registration",
            "callsign",
            "airline_name",
            "airline_icao",
            "aircraft_type",
            "model",
            "manufacturer",
            "operator",
            "observed_at",
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def operator_resolved(self) -> bool:
        """True when the operator/airline is known from the ADS-B record."""
        return bool(self.airline_name or self.operator or self.airline_icao)


@dataclass
class RegistrationDetail:
    """Aircraft record from GET /v3/aircraft/registration/{reg}.

    615k+ aircraft: manufacturer, model, operator. Used sparingly — only
    to resolve the operator of aircraft whose ADS-B record left it blank.
    """

    registration: str = ""
    manufacturer: str = ""
    model: str = ""
    operator: str = ""
    aircraft_type: str = ""
    icao24: str = ""

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> "RegistrationDetail":
        def _get(*keys: str, default: Any = "") -> Any:
            for k in keys:
                if k in data and data[k] not in (None, ""):
                    return data[k]
            return default

        return cls(
            registration=_to_str(_get("registration", "reg", "tail_number")),
            manufacturer=_to_str(_get("manufacturer", "make")),
            model=_to_str(_get("model", "aircraft_model", "type")),
            operator=_to_str(_get("operator", "airline", "owner")),
            aircraft_type=_to_str(_get("aircraft_type", "type", "icao_type")),
            icao24=_to_str(_get("icao24", "icao", "hex")),
        )


@dataclass
class Airline:
    """Airline record from GET /airlines/search (icao OR iata, never both)."""

    name: str = ""
    icao: str = ""
    iata: str = ""
    country: str = ""

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> "Airline":
        def _get(*keys: str, default: Any = "") -> Any:
            for k in keys:
                if k in data and data[k] not in (None, ""):
                    return data[k]
            return default

        return cls(
            name=_to_str(_get("name", "airline_name")),
            icao=_to_str(_get("icao", "icao_code")),
            iata=_to_str(_get("iata", "iata_code")),
            country=_to_str(_get("country")),
        )


@dataclass
class DataQualityRow:
    """One data-quality check result, written to SKYLINK_Data_Quality."""

    check_name: str = ""
    checked_field: str = ""
    total_rows: int = 0
    failed_rows: int = 0
    pass_rate_pct: float = 0.0
    status: str = ""
    observed_at: str = ""

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "check_name",
            "checked_field",
            "total_rows",
            "failed_rows",
            "pass_rate_pct",
            "status",
            "observed_at",
        ]

    def to_sheet_row(self) -> list[Any]:
        return [
            self.check_name,
            self.checked_field,
            self.total_rows,
            self.failed_rows,
            self.pass_rate_pct,
            self.status,
            self.observed_at,
        ]


@dataclass
class IngestionLogRow:
    """One pipeline-run log entry, written to SKYLINK_Ingestion_Log."""

    run_at: str = ""
    source: str = "skylink"
    airlines_targeted: int = 0
    adsb_requests: int = 0
    registration_lookups: int = 0
    aircraft_fetched: int = 0
    aircraft_written: int = 0
    operators_resolved: int = 0
    status: str = ""
    notes: str = ""

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "run_at",
            "source",
            "airlines_targeted",
            "adsb_requests",
            "registration_lookups",
            "aircraft_fetched",
            "aircraft_written",
            "operators_resolved",
            "status",
            "notes",
        ]

    def to_sheet_row(self) -> list[Any]:
        return [
            self.run_at,
            self.source,
            self.airlines_targeted,
            self.adsb_requests,
            self.registration_lookups,
            self.aircraft_fetched,
            self.aircraft_written,
            self.operators_resolved,
            self.status,
            self.notes,
        ]
