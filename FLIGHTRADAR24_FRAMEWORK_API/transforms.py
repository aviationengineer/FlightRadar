"""Transform helpers: Flight objects → sheet-ready rows."""

from __future__ import annotations

from typing import Any

from .models import Flight


def flights_to_rows(flights: list[Flight]) -> list[list[Any]]:
    """Convert flights to 2D rows matching Flight.sheet_headers()."""
    return [f.to_sheet_row() for f in flights]


def dedupe_by_fr24_id(flights: list[Flight]) -> list[Flight]:
    seen: set[str] = set()
    out: list[Flight] = []
    for f in flights:
        key = f.fr24_id or f.callsign
        if key and key not in seen:
            seen.add(key)
            out.append(f)
    return out


def filter_by_altitude(
    flights: list[Flight],
    min_ft: int | None = None,
    max_ft: int | None = None,
) -> list[Flight]:
    out = []
    for f in flights:
        if f.altitude_ft is None:
            continue
        if min_ft is not None and f.altitude_ft < min_ft:
            continue
        if max_ft is not None and f.altitude_ft > max_ft:
            continue
        out.append(f)
    return out
