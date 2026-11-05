"""Transform helpers: Skylink records → normalised, sheet-ready rows."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .models import AircraftObservation, DataQualityRow

_REG_CLEAN = re.compile(r"[^A-Z0-9]")


def normalize_registration(reg: str) -> str:
    """Upper-case, strip spaces/dashes: 'c-frsr' → 'CFRSR'."""
    return _REG_CLEAN.sub("", (reg or "").upper())


def normalize_callsign(callsign: str) -> str:
    """Upper-case, strip whitespace."""
    return (callsign or "").upper().strip()


def normalize_observations(
    observations: list[AircraftObservation],
) -> list[AircraftObservation]:
    """Normalise registrations/callsigns and stamp missing observed_at."""
    now_iso = datetime.now(timezone.utc).isoformat()
    for obs in observations:
        obs.registration = normalize_registration(obs.registration)
        obs.callsign = normalize_callsign(obs.callsign)
        obs.icao24 = (obs.icao24 or "").lower().strip()
        obs.airline_name = (obs.airline_name or "").strip()
        obs.airline_icao = (obs.airline_icao or "").upper().strip()
        obs.aircraft_type = (obs.aircraft_type or "").strip()
        if not obs.operator and obs.airline_name:
            obs.operator = obs.airline_name
        if not obs.observed_at:
            obs.observed_at = now_iso
    return observations


def dedupe_by_icao24(
    observations: list[AircraftObservation],
) -> list[AircraftObservation]:
    """One row per airframe per snapshot (keyed on icao24, else registration)."""
    seen: set[str] = set()
    out: list[AircraftObservation] = []
    for obs in observations:
        key = obs.icao24 or obs.registration or obs.callsign
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            out.append(obs)
    return out


def observations_to_rows(
    observations: list[AircraftObservation],
) -> list[list[Any]]:
    return [o.to_sheet_row() for o in observations]


def summarize_by_airline(
    observations: list[AircraftObservation],
) -> list[dict[str, Any]]:
    """Per-airline active-fleet summary: aircraft seen airborne, by type."""
    counts: Counter[tuple[str, str]] = Counter()
    types: dict[str, Counter[str]] = {}
    for obs in observations:
        airline = obs.airline_name or obs.operator or obs.airline_icao or "UNKNOWN"
        counts[(airline, obs.airline_icao)] += 1
        types.setdefault(airline, Counter())[obs.aircraft_type or "UNKNOWN"] += 1
    summary = []
    for (airline, icao), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        type_breakdown = ", ".join(
            f"{t} x{c}" for t, c in types[airline].most_common()
        )
        summary.append({
            "airline_name": airline,
            "airline_icao": icao,
            "aircraft_observed": n,
            "aircraft_types": type_breakdown,
        })
    return summary


def run_quality_checks(
    observations: list[AircraftObservation],
    observed_at: str | None = None,
) -> list[DataQualityRow]:
    """Completeness / uniqueness checks over one snapshot."""
    now_iso = observed_at or datetime.now(timezone.utc).isoformat()
    total = len(observations)
    rows: list[DataQualityRow] = []

    def _check(name: str, field: str, failed: int) -> None:
        rate = round(100.0 * (total - failed) / total, 2) if total else 100.0
        rows.append(DataQualityRow(
            check_name=name,
            checked_field=field,
            total_rows=total,
            failed_rows=failed,
            pass_rate_pct=rate,
            status="PASS" if rate >= 95 else ("WARN" if rate >= 80 else "FAIL"),
            observed_at=now_iso,
        ))

    _check("registration_present", "registration",
           sum(1 for o in observations if not o.registration))
    _check("icao24_present", "icao24",
           sum(1 for o in observations if not o.icao24))
    _check("airline_resolved", "airline_name",
           sum(1 for o in observations if not o.operator_resolved))
    _check("aircraft_type_present", "aircraft_type",
           sum(1 for o in observations if not o.aircraft_type))
    _check("callsign_present", "callsign",
           sum(1 for o in observations if not o.callsign))
    # Uniqueness: duplicate icao24s after dedupe should be zero.
    seen: Counter[str] = Counter(
        o.icao24 for o in observations if o.icao24
    )
    dupes = sum(c - 1 for c in seen.values() if c > 1)
    _check("icao24_unique", "icao24", dupes)
    return rows
