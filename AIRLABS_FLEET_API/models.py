"""Domain models for AirLabs fleet data.

Source: GET /fleets — https://airlabs.co/docs/fleets
Response envelope: {"request": {...}, "response": [ {...}, ... ]}
Per-aircraft fields used here: hex, reg_number, airline_icao,
airline_iata, icao (aircraft ICAO type), model, manufacturer, age.
The endpoint returns no airline *name*; that is enriched from /airlines.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class FleetAircraft:
    """One normalised fleet record (one aircraft)."""

    hex: str = ""
    reg_number: str = ""
    airline_icao: str = ""
    airline_iata: str = ""
    airline_name: str = ""
    icao_type: str = ""
    model: str = ""
    manufacturer: str = ""
    age: Optional[int] = None
    fetched_at: str = ""

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> "FleetAircraft":
        """Create FleetAircraft from an AirLabs /fleets record.

        Defensive: accepts several key spellings, upper-cases codes,
        strips whitespace, coerces age to int (or None).
        """
        def _get(*keys: str, default: Any = "") -> Any:
            for k in keys:
                if k in data and data[k] not in (None, ""):
                    return data[k]
            return default

        def _code(*keys: str) -> str:
            v = _get(*keys, default="")
            return str(v).strip().upper() if v not in (None, "") else ""

        return cls(
            hex=_code("hex", "icao24"),
            reg_number=_code("reg_number", "registration", "reg"),
            airline_icao=_code("airline_icao", "operator_icao"),
            airline_iata=_code("airline_iata", "operator_iata"),
            airline_name=str(_get("airline_name", "name", default="")).strip(),
            icao_type=_code("icao", "icao_type", "aircraft_icao", "type_icao"),
            model=str(_get("model", default="")).strip(),
            manufacturer=str(_get("manufacturer", default="")).strip().upper(),
            age=_to_int(_get("age", default=None)),
            fetched_at=str(_get("fetched_at", default="")),
        )

    def to_sheet_row(self) -> list[Any]:
        """Row in the order defined by sheet_headers()."""
        return [
            self.hex,
            self.reg_number,
            self.airline_icao,
            self.airline_iata,
            self.airline_name,
            self.icao_type,
            self.model,
            self.manufacturer,
            self.age if self.age is not None else "",
            self.fetched_at,
        ]

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "hex",
            "reg_number",
            "airline_icao",
            "airline_iata",
            "airline_name",
            "icao_type",
            "model",
            "manufacturer",
            "age",
            "fetched_at",
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def key(self) -> str:
        """Stable dedupe/merge key: hex first, registration as fallback."""
        return self.hex or self.reg_number


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
