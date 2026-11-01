"""Domain models for FlightRadar24 data."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class Flight:
    """Normalised live flight position."""

    fr24_id: str = ""
    callsign: str = ""
    flight_number: str = ""
    registration: str = ""
    aircraft_type: str = ""
    origin_iata: str = ""
    origin_icao: str = ""
    destination_iata: str = ""
    destination_icao: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_ft: Optional[int] = None
    ground_speed_kts: Optional[int] = None
    heading_deg: Optional[int] = None
    squawk: str = ""
    timestamp_utc: str = ""
    airline_icao: str = ""

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> "Flight":
        """Create Flight from FR24 API dict (light or full).

        The API returns slightly different shapes between light/full.
        This is defensive: it checks several common key names.
        """
        def _get(*keys: str, default: Any = "") -> Any:
            for k in keys:
                if k in data and data[k] not in (None, ""):
                    return data[k]
            return default

        # Origin/destination may be nested dicts or flat codes
        origin = _get("orig_iata", "origin_iata", "orig", default={})
        dest = _get("dest_iata", "destination_iata", "dest", default={})

        def _code(obj: Any, *keys: str) -> str:
            if isinstance(obj, dict):
                for k in keys:
                    if obj.get(k):
                        return str(obj[k])
                return ""
            return str(obj) if obj else ""

        return cls(
            fr24_id=str(_get("fr24_id", "id", "flight_id", default="")),
            callsign=str(_get("callsign", "call_sign", default="")),
            flight_number=str(_get("flight", "flight_number", "number", default="")),
            registration=str(_get("reg", "registration", default="")),
            aircraft_type=str(_get("aircraft_type", "type", "ac_type", default="")),
            origin_iata=_code(origin, "iata", "code") or str(_get("orig_iata", default="")),
            origin_icao=_code(origin, "icao") or str(_get("orig_icao", default="")),
            destination_iata=_code(dest, "iata", "code") or str(_get("dest_iata", default="")),
            destination_icao=_code(dest, "icao") or str(_get("dest_icao", default="")),
            latitude=_to_float(_get("lat", "latitude", default=None)),
            longitude=_to_float(_get("lon", "lng", "longitude", default=None)),
            altitude_ft=_to_int(_get("alt", "altitude", default=None)),
            ground_speed_kts=_to_int(_get("gspeed", "ground_speed", "speed", "spd", default=None)),
            heading_deg=_to_int(_get("heading", "hdg", "track", default=None)),
            squawk=str(_get("squawk", default="")),
            timestamp_utc=str(_get("timestamp", "datetime", "time", default="")),
            airline_icao=str(_get("airline_icao", "operator_icao", default="")),
        )

    def to_sheet_row(self) -> list[Any]:
        """Row in the order defined by sheet_headers()."""
        return [
            self.timestamp_utc,
            self.fr24_id,
            self.callsign,
            self.flight_number,
            self.registration,
            self.aircraft_type,
            self.airline_icao,
            self.origin_iata,
            self.origin_icao,
            self.destination_iata,
            self.destination_icao,
            self.latitude,
            self.longitude,
            self.altitude_ft,
            self.ground_speed_kts,
            self.heading_deg,
            self.squawk,
        ]

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "timestamp_utc",
            "fr24_id",
            "callsign",
            "flight_number",
            "registration",
            "aircraft_type",
            "airline_icao",
            "origin_iata",
            "origin_icao",
            "destination_iata",
            "destination_icao",
            "latitude",
            "longitude",
            "altitude_ft",
            "ground_speed_kts",
            "heading_deg",
            "squawk",
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
