"""Transform helpers: FleetAircraft objects -> sheet-ready rows,
dedupe/merge, and data-quality metrics.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .models import FleetAircraft


def aircraft_to_rows(aircraft: list[FleetAircraft]) -> list[list[Any]]:
    """Convert aircraft to 2D rows matching FleetAircraft.sheet_headers()."""
    return [a.to_sheet_row() for a in aircraft]


def rows_to_aircraft(rows: list[list[Any]]) -> list[FleetAircraft]:
    """Parse sheet rows (with header row) back into FleetAircraft objects.

    Used when merging a weekly refresh into the existing sheet contents.
    Rows that do not match the header layout are skipped.
    """
    if not rows:
        return []
    header = [str(h).strip() for h in rows[0]]
    expected = FleetAircraft.sheet_headers()
    if header[: len(expected)] != expected:
        return []
    out: list[FleetAircraft] = []
    for row in rows[1:]:
        if not row or all(v in (None, "") for v in row):
            continue
        padded = list(row) + [""] * (len(expected) - len(row))
        rec = dict(zip(expected, padded))
        try:
            age = int(float(rec["age"])) if str(rec["age"]).strip() not in ("",) else None
        except (TypeError, ValueError):
            age = None
        out.append(FleetAircraft(
            hex=str(rec["hex"]).strip().upper(),
            reg_number=str(rec["reg_number"]).strip().upper(),
            airline_icao=str(rec["airline_icao"]).strip().upper(),
            airline_iata=str(rec["airline_iata"]).strip().upper(),
            airline_name=str(rec["airline_name"]).strip(),
            icao_type=str(rec["icao_type"]).strip().upper(),
            model=str(rec["model"]).strip(),
            manufacturer=str(rec["manufacturer"]).strip().upper(),
            age=age,
            fetched_at=str(rec["fetched_at"]).strip(),
        ))
    return out


def normalize_aircraft(aircraft: list[FleetAircraft],
                       fetched_at: str | None = None) -> list[FleetAircraft]:
    """Stamp fetched_at (UTC now when missing) and drop empty records."""
    stamp = fetched_at or datetime.now(timezone.utc).isoformat()
    out: list[FleetAircraft] = []
    for a in aircraft:
        if not a.key:
            continue
        if not a.fetched_at:
            a.fetched_at = stamp
        out.append(a)
    return out


def dedupe_by_hex(aircraft: list[FleetAircraft]) -> list[FleetAircraft]:
    """Dedupe on hex (fallback reg_number), keeping the first occurrence."""
    seen: set[str] = set()
    out: list[FleetAircraft] = []
    for a in aircraft:
        key = a.key
        if key and key not in seen:
            seen.add(key)
            out.append(a)
    return out


def filter_by_airline(aircraft: list[FleetAircraft],
                      iata: str | None = None,
                      icao: str | None = None) -> list[FleetAircraft]:
    out = []
    for a in aircraft:
        if iata and a.airline_iata != iata.strip().upper():
            continue
        if icao and a.airline_icao != icao.strip().upper():
            continue
        out.append(a)
    return out


def merge_fleets(existing: list[FleetAircraft],
                 fresh: list[FleetAircraft]) -> list[FleetAircraft]:
    """Upsert fresh records into the existing fleet by hex/reg key.

    Fresh records replace existing ones with the same key; new keys are
    appended. Order: existing order first, then new aircraft.
    """
    by_key: dict[str, FleetAircraft] = {}
    order: list[str] = []
    for a in existing:
        if a.key and a.key not in by_key:
            order.append(a.key)
        if a.key:
            by_key[a.key] = a
    for a in fresh:
        if not a.key:
            continue
        if a.key not in by_key:
            order.append(a.key)
        by_key[a.key] = a
    return [by_key[k] for k in order]


def enrich_airline_names(aircraft: list[FleetAircraft],
                         names: dict[str, str]) -> list[FleetAircraft]:
    """Fill airline_name from a {IATA|ICAO code: name} map when blank."""
    for a in aircraft:
        if not a.airline_name:
            a.airline_name = (
                names.get(a.airline_iata)
                or names.get(a.airline_icao)
                or ""
            )
    return aircraft


def compute_quality_metrics(aircraft: list[FleetAircraft],
                            duplicates_removed: int = 0) -> dict[str, Any]:
    """Data-quality summary for a fleet snapshot."""
    total = len(aircraft)
    ages = [a.age for a in aircraft if a.age is not None]
    metrics: dict[str, Any] = {
        "total_aircraft": total,
        "distinct_hex": len({a.hex for a in aircraft if a.hex}),
        "distinct_registrations": len({a.reg_number for a in aircraft if a.reg_number}),
        "distinct_airlines_iata": len({a.airline_iata for a in aircraft if a.airline_iata}),
        "distinct_manufacturers": len({a.manufacturer for a in aircraft if a.manufacturer}),
        "distinct_icao_types": len({a.icao_type for a in aircraft if a.icao_type}),
        "missing_reg_number": sum(1 for a in aircraft if not a.reg_number),
        "missing_hex": sum(1 for a in aircraft if not a.hex),
        "missing_airline_iata": sum(1 for a in aircraft if not a.airline_iata),
        "missing_airline_icao": sum(1 for a in aircraft if not a.airline_icao),
        "missing_model": sum(1 for a in aircraft if not a.model),
        "missing_manufacturer": sum(1 for a in aircraft if not a.manufacturer),
        "missing_age": sum(1 for a in aircraft if a.age is None),
        "duplicate_hex_removed": duplicates_removed,
        "age_lt_0_or_gt_60": sum(1 for a in ages if a < 0 or a > 60),
        "avg_age_years": round(sum(ages) / len(ages), 1) if ages else "",
        "pct_with_age": round(100.0 * len(ages) / total, 1) if total else 0.0,
    }
    return metrics


def quality_metrics_to_rows(metrics: dict[str, Any],
                            checked_at: str | None = None) -> list[list[Any]]:
    """Quality metrics dict -> [metric, value, checked_at_utc] rows."""
    stamp = checked_at or datetime.now(timezone.utc).isoformat()
    return [[k, v, stamp] for k, v in metrics.items()]


def top_airlines_by_fleet(aircraft: list[FleetAircraft],
                          limit: int = 10) -> list[tuple[str, int]]:
    """Most common airline IATA codes with aircraft counts."""
    counts = Counter(a.airline_iata for a in aircraft if a.airline_iata)
    return counts.most_common(limit)
