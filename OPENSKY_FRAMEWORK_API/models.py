"""Domain models for OpenSky Network data.

API: https://opensky-network.org/data/api
States vector indices:
0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
5 longitude, 6 latitude, 7 baro_altitude, 8 on_ground, 9 velocity,
10 true_track, 11 vertical_rate, 12 sensors, 13 geo_altitude, 14 squawk,
15 spi, 16 position_source, 17 category
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class OpenSkyState:
    icao24: str = ""
    callsign: str = ""
    origin_country: str = ""
    time_position: Optional[int] = None
    last_contact: Optional[int] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    baro_altitude_m: Optional[float] = None
    on_ground: bool = False
    velocity_ms: Optional[float] = None
    true_track_deg: Optional[float] = None
    vertical_rate_ms: Optional[float] = None
    geo_altitude_m: Optional[float] = None
    squawk: str = ""
    position_source: Optional[int] = None
    category: Optional[int] = None

    @classmethod
    def from_vector(cls, v: list[Any]) -> "OpenSkyState":
        # pad to 18
        v = list(v) + [None] * (18 - len(v))
        return cls(
            icao24=str(v[0] or "").strip(),
            callsign=str(v[1] or "").strip(),
            origin_country=str(v[2] or "").strip(),
            time_position=_to_int(v[3]),
            last_contact=_to_int(v[4]),
            longitude=_to_float(v[5]),
            latitude=_to_float(v[6]),
            baro_altitude_m=_to_float(v[7]),
            on_ground=bool(v[8]),
            velocity_ms=_to_float(v[9]),
            true_track_deg=_to_float(v[10]),
            vertical_rate_ms=_to_float(v[11]),
            geo_altitude_m=_to_float(v[13]),
            squawk=str(v[14] or "").strip(),
            position_source=_to_int(v[16]),
            category=_to_int(v[17]),
        )

    def to_sheet_row(self) -> list[Any]:
        return [
            self.icao24,
            self.callsign,
            self.origin_country,
            self.latitude,
            self.longitude,
            self.baro_altitude_m,
            self.geo_altitude_m,
            self.velocity_ms,
            self.true_track_deg,
            self.vertical_rate_ms,
            self.on_ground,
            self.squawk,
            self.time_position,
            self.last_contact,
            self.category,
        ]

    @staticmethod
    def sheet_headers() -> list[str]:
        return [
            "icao24", "callsign", "origin_country",
            "latitude", "longitude",
            "baro_altitude_m", "geo_altitude_m",
            "velocity_ms", "true_track_deg", "vertical_rate_ms",
            "on_ground", "squawk",
            "time_position", "last_contact", "category",
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
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
