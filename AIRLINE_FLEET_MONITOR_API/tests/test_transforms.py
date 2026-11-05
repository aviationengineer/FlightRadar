"""Unit tests for AFM models + transforms (no network)."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))

from AIRLINE_FLEET_MONITOR_API.models import AirlineFleet
from AIRLINE_FLEET_MONITOR_API.transforms import (
    dedupe_fleets,
    export_to_fleets,
    fleets_to_rows,
    quality_summary,
    run_quality_checks,
    total_airframes,
)

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_airlines.json")
FETCHED = "2026-11-05T00:00:00+00:00"


def _sample():
    with open(SAMPLE_PATH) as fh:
        return json.load(fh)


# --- models ---------------------------------------------------------------

def test_from_export_dict_maps_fields():
    f = AirlineFleet.from_export_dict(_sample()[0], fetched_at=FETCHED)
    assert f.airline == "Delta Air Lines"
    assert (f.iata, f.icao, f.country) == ("DL", "DAL", "United States")
    assert (f.active, f.idle_7_29d, f.stored_30d_plus, f.total) == (1388, 0, 0, 1388)
    assert f.average_age == 11.2
    assert f.coverage_confidence == "high"
    assert f.hubs == "KATL,KJFK,KLAX,KDTW,KMSP,KSLC,KBOS,KSEA"
    assert f.fetched_at == FETCHED


def test_from_export_dict_total_falls_back_to_split_sum():
    rec = dict(_sample()[0])
    rec["observed_fleet_count"] = None
    rec["active_count"] = 100
    rec["idle_count"] = 5
    rec["stored_count"] = 2
    f = AirlineFleet.from_export_dict(rec)
    assert f.total == 107


def test_sheet_row_matches_headers():
    f = AirlineFleet.from_export_dict(_sample()[0], fetched_at=FETCHED)
    row = f.to_sheet_row()
    assert len(row) == len(AirlineFleet.sheet_headers())
    assert row[0] == "Delta Air Lines" and row[7] == 1388 and row[-1] == FETCHED


def test_from_api_dict_handles_hubs_json_string():
    rec = dict(_sample()[0])
    rec["hubs"] = '["KATL", "KJFK"]'
    f = AirlineFleet.from_api_dict({"success": True, "data": rec})
    assert f.hubs == "KATL,KJFK"


# --- transforms -----------------------------------------------------------

def test_export_to_fleets_filters_defunct():
    fleets = export_to_fleets(_sample(), fetched_at=FETCHED)
    names = [f.airline for f in fleets]
    assert "Federal Express" not in names  # defunct, despite 483 observed
    assert "Delta Air Lines" in names
    assert len(fleets) == 4  # 5 sample records, 1 defunct


def test_export_to_fleets_sorted_by_total_desc():
    fleets = export_to_fleets(_sample(), fetched_at=FETCHED)
    totals = [f.total for f in fleets]
    assert totals == sorted(totals, reverse=True)
    assert fleets[0].airline == "Delta Air Lines"


def test_dedupe_keeps_largest_total():
    a = AirlineFleet(airline="Test Air", icao="TST", total=10)
    b = AirlineFleet(airline="Test Air", icao="TST", total=25)
    out = dedupe_fleets([a, b])
    assert len(out) == 1 and out[0].total == 25


def test_total_airframes():
    fleets = export_to_fleets(_sample(), fetched_at=FETCHED)
    assert total_airframes(fleets) == 1388 + 1239 + 0 + 145


def test_fleets_to_rows_shape():
    fleets = export_to_fleets(_sample(), fetched_at=FETCHED)
    rows = fleets_to_rows(fleets)
    assert len(rows) == len(fleets)
    assert all(len(r) == len(AirlineFleet.sheet_headers()) for r in rows)


# --- quality checks -------------------------------------------------------

def test_quality_flags_all_zero_idle_stored_as_warn():
    fleets = export_to_fleets(_sample(), fetched_at=FETCHED)
    checks = {c.check: c for c in run_quality_checks(_sample(), fleets, FETCHED)}
    assert checks["idle_split_populated"].result == "WARN"
    assert checks["stored_split_populated"].result == "WARN"
    assert checks["split_sums_to_total"].result == "PASS"


def test_quality_flags_placeholder_avg_age():
    fleets = export_to_fleets(_sample(), fetched_at=FETCHED)
    checks = {c.check: c for c in run_quality_checks(_sample(), fleets, FETCHED)}
    assert checks["average_age_variance"].result == "WARN"
    assert "11.2" in checks["average_age_variance"].value


def test_quality_counts_missing_iata():
    fleets = export_to_fleets(_sample(), fetched_at=FETCHED)
    checks = {c.check: c for c in run_quality_checks(_sample(), fleets, FETCHED)}
    # sample has one active carrier with no IATA (Skywest Airlines)
    assert checks["iata_coverage"].result == "WARN"
    assert checks["icao_coverage"].result == "PASS"
    assert checks["defunct_airlines_excluded"].value == "1"


def test_quality_summary_counts():
    fleets = export_to_fleets(_sample(), fetched_at=FETCHED)
    summary = quality_summary(run_quality_checks(_sample(), fleets, FETCHED))
    assert summary["FAIL"] == 0
    assert summary["WARN"] >= 3  # idle, stored, avg_age, iata
    assert summary["PASS"] > 0
