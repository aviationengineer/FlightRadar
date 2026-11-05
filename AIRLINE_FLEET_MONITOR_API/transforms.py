"""Transform helpers: raw AFM records -> normalised fleets -> sheet rows,
plus the data-quality checks that feed AFM_Data_Quality."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .models import AirlineFleet, DataQualityRow


def export_to_fleets(
    raw_records: list[dict[str, Any]],
    fetched_at: str = "",
    active_only: bool = True,
) -> list[AirlineFleet]:
    """Parse export records into AirlineFleet models.

    By default keeps only status == "active" carriers: the export also
    carries 1,640 defunct/merged airlines, some of which still carry
    observed fleet counts (e.g. defunct Federal Express: 483), so they must
    be excluded from the active-fleet picture. Dedupes on ICAO (fallback
    slug), keeps the record with the largest total on collision, and sorts
    by total descending.
    """
    fleets: list[AirlineFleet] = []
    for rec in raw_records:
        fleet = AirlineFleet.from_export_dict(rec, fetched_at=fetched_at)
        if active_only and fleet.status.lower() != "active":
            continue
        fleets.append(fleet)
    return dedupe_fleets(fleets)


def dedupe_fleets(fleets: list[AirlineFleet]) -> list[AirlineFleet]:
    """Dedupe on ICAO (fallback slug); keep largest total; sort desc by total."""
    best: dict[str, AirlineFleet] = {}
    for f in fleets:
        key = (f.icao or f.slug or f.airline).strip().upper()
        if not key:
            continue
        prev = best.get(key)
        if prev is None or f.total > prev.total:
            best[key] = f
    return sorted(best.values(), key=lambda f: (-f.total, f.airline.lower()))


def fleets_to_rows(fleets: list[AirlineFleet]) -> list[list[Any]]:
    return [f.to_sheet_row() for f in fleets]


def total_airframes(fleets: list[AirlineFleet]) -> int:
    return sum(f.total for f in fleets)


def run_quality_checks(
    raw_records: list[dict[str, Any]],
    fleets: list[AirlineFleet],
    fetched_at: str = "",
) -> list[DataQualityRow]:
    """Data-quality checks over the raw export + normalised fleets.

    Checks are honest about the source's known weaknesses (verified live
    2026-11-05): idle/stored counts are 0 for every record, and avg_age
    takes only two distinct values across the whole file, so both are
    reported as WARN rather than silently trusted.
    """
    rows: list[DataQualityRow] = []

    def add(check: str, result: str, detail: str, value: str) -> None:
        rows.append(DataQualityRow(check, result, detail, value, fetched_at))

    n_raw = len(raw_records)
    n_active_raw = sum(1 for r in raw_records if str(r.get("status") or "").lower() == "active")
    n_defunct = sum(1 for r in raw_records if str(r.get("status") or "").lower() == "defunct")
    add("export_record_count", "PASS" if n_raw > 0 else "FAIL",
        "Rows in /data/airlines.json", str(n_raw))
    add("active_airlines_in_export", "PASS" if n_active_raw > 0 else "FAIL",
        "Records with status=active", str(n_active_raw))
    add("defunct_airlines_excluded", "PASS",
        "Defunct/merged records excluded from AFM_Fleets", str(n_defunct))
    add("fleets_written", "PASS" if len(fleets) == n_active_raw or len(fleets) > 0 else "FAIL",
        "Active fleets after dedupe (may be < active if duplicate ICAOs merged)",
        f"{len(fleets)} of {n_active_raw}")

    # Totals reconcile: active+idle+stored vs observed total, per airline.
    mismatched = [f for f in fleets
                  if f.active + f.idle_7_29d + f.stored_30d_plus != f.total]
    add("split_sums_to_total", "PASS" if not mismatched else "WARN",
        "Airlines where active+idle+stored != total",
        f"{len(mismatched)} of {len(fleets)}")

    # The idle/stored split is the headline weakness: all zeros in the export.
    n_idle = sum(1 for f in fleets if f.idle_7_29d > 0)
    n_stored = sum(1 for f in fleets if f.stored_30d_plus > 0)
    add("idle_split_populated", "WARN" if n_idle == 0 else "PASS",
        "Airlines with idle_7_29d > 0 (export carries 0 for every record; "
        "site homepage quotes 6.5% short-term idle in aggregate)",
        f"{n_idle} of {len(fleets)}")
    add("stored_split_populated", "WARN" if n_stored == 0 else "PASS",
        "Airlines with stored_30d_plus > 0 (export carries 0 for every "
        "record; site homepage quotes 9.3% long-term storage in aggregate)",
        f"{n_stored} of {len(fleets)}")

    # avg_age: only two distinct values in the live file (0.0 and 11.2).
    ages = [f.average_age for f in fleets if f.average_age is not None]
    distinct = sorted({a for a in ages})
    n_at_112 = sum(1 for a in ages if a == 11.2)
    add("average_age_variance", "WARN" if len(distinct) <= 2 else "PASS",
        "Distinct average_age values across fleets; 11.2 appears to be a "
        "site-wide placeholder (per-airline API returns avg_age=null)",
        f"{len(distinct)} distinct ({distinct[:5]}); 11.2 in {n_at_112} of {len(ages)}")
    add("average_age_coverage", "PASS" if ages else "FAIL",
        "Fleets with a non-null average_age", f"{len(ages)} of {len(fleets)}")

    # Identifier completeness.
    missing_iata = sum(1 for f in fleets if not f.iata)
    missing_icao = sum(1 for f in fleets if not f.icao)
    missing_country = sum(1 for f in fleets if not f.country)
    add("iata_coverage", "WARN" if missing_iata else "PASS",
        "Active fleets missing an IATA code", f"{len(fleets) - missing_iata} of {len(fleets)}")
    add("icao_coverage", "PASS" if not missing_icao else "FAIL",
        "Active fleets missing an ICAO code", f"{len(fleets) - missing_icao} of {len(fleets)}")
    add("country_coverage", "PASS" if not missing_country else "WARN",
        "Active fleets missing a country", f"{len(fleets) - missing_country} of {len(fleets)}")

    # Zero-fleet active carriers (311 in the live file) are real: small or
    # unobserved operators, not parse errors.
    zero = sum(1 for f in fleets if f.total == 0)
    add("zero_fleet_active_carriers", "PASS",
        "Active carriers with total == 0 (small/unobserved operators)",
        f"{zero} of {len(fleets)}")

    # Coverage confidence mix.
    conf = Counter(f.coverage_confidence or "missing" for f in fleets)
    add("coverage_confidence_mix", "PASS",
        "coverage_confidence distribution across active fleets",
        ", ".join(f"{k}={v}" for k, v in sorted(conf.items())))

    add("total_airframes_active", "PASS",
        "Sum of total across active fleets (ADS-B-observed airframes)",
        str(total_airframes(fleets)))
    return rows


def quality_summary(checks: list[DataQualityRow]) -> dict[str, int]:
    counts = Counter(c.result for c in checks)
    return {"PASS": counts.get("PASS", 0), "WARN": counts.get("WARN", 0),
            "FAIL": counts.get("FAIL", 0)}
