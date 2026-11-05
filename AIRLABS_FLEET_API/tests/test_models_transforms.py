from __future__ import annotations

import pytest

from AIRLABS_FLEET_API.models import FleetAircraft
from AIRLABS_FLEET_API.transforms import (
    aircraft_to_rows,
    compute_quality_metrics,
    dedupe_by_hex,
    enrich_airline_names,
    merge_fleets,
    normalize_aircraft,
    quality_metrics_to_rows,
    rows_to_aircraft,
)


def _ac(**overrides):
    base = {"hex": "A9D286", "reg_number": "N732AN", "airline_icao": "AAL",
            "airline_iata": "AA", "icao_type": "77W",
            "model": "Boeing 777-300ER pax", "manufacturer": "BOEING",
            "age": 11, "fetched_at": "2026-11-05T00:00:00+00:00"}
    base.update(overrides)
    return FleetAircraft(**base)


def test_from_api_dict_normalises_codes_and_age():
    raw = {"hex": "a9d286", "reg_number": " n732an ", "airline_iata": "aa",
           "airline_icao": "aal", "icao": "77w", "model": " Boeing 777 ",
           "manufacturer": "boeing", "age": "11"}
    a = FleetAircraft.from_api_dict(raw)
    assert a.hex == "A9D286"
    assert a.reg_number == "N732AN"
    assert a.airline_iata == "AA"
    assert a.icao_type == "77W"
    assert a.manufacturer == "BOEING"
    assert a.age == 11
    assert a.model == "Boeing 777"


def test_from_api_dict_missing_fields_become_empty_or_none():
    a = FleetAircraft.from_api_dict({"hex": "ABC123"})
    assert a.reg_number == ""
    assert a.age is None
    assert a.airline_name == ""
    assert a.key == "ABC123"


def test_sheet_row_matches_headers():
    a = _ac()
    row = a.to_sheet_row()
    assert len(row) == len(FleetAircraft.sheet_headers()) == 10
    assert row[0] == "A9D286" and row[1] == "N732AN" and row[8] == 11


def test_dedupe_by_hex_keeps_first():
    fleet = [_ac(), _ac(reg_number="N999AA"), _ac(hex="BBBBBB")]
    assert len(dedupe_by_hex(fleet)) == 2
    assert dedupe_by_hex(fleet)[0].reg_number == "N732AN"


def test_normalize_stamps_fetched_at_and_drops_empty():
    fleet = normalize_aircraft([_ac(fetched_at=""), FleetAircraft()])
    assert len(fleet) == 1
    assert fleet[0].fetched_at != ""


def test_merge_upserts_by_hex_and_appends_new():
    existing = [_ac(), _ac(hex="BBBBBB", reg_number="N111AA")]
    fresh = [_ac(model="Boeing 777-300ER updated"), _ac(hex="CCCCCC")]
    merged = merge_fleets(existing, fresh)
    assert len(merged) == 3
    assert merged[0].model == "Boeing 777-300ER updated"
    assert merged[0].hex == "A9D286"  # position preserved
    assert merged[2].hex == "CCCCCC"


def test_rows_round_trip():
    fleet = [_ac(), _ac(hex="BBBBBB", reg_number="N111AA", age=None)]
    rows = [FleetAircraft.sheet_headers()] + aircraft_to_rows(fleet)
    back = rows_to_aircraft(rows)
    assert len(back) == 2
    assert back[0].hex == "A9D286" and back[0].age == 11
    assert back[1].age is None


def test_quality_metrics_counts_gaps():
    fleet = [_ac(), _ac(hex="BBBBBB", reg_number="", model="", age=None),
             _ac(hex="CCCCCC", reg_number="N222BB", age=99)]
    m = compute_quality_metrics(fleet, duplicates_removed=2)
    assert m["total_aircraft"] == 3
    assert m["missing_reg_number"] == 1
    assert m["missing_model"] == 1
    assert m["missing_age"] == 1
    assert m["duplicate_hex_removed"] == 2
    assert m["age_lt_0_or_gt_60"] == 1
    assert m["pct_with_age"] == pytest.approx(66.7)
    rows = quality_metrics_to_rows(m, checked_at="2026-11-05T00:00:00+00:00")
    assert rows[0] == ["total_aircraft", 3, "2026-11-05T00:00:00+00:00"]


def test_enrich_airline_names_only_fills_blanks():
    fleet = [_ac(), _ac(hex="BBBBBB", airline_iata="FR", airline_name="Ryanair")]
    enrich_airline_names(fleet, {"AA": "American Airlines", "FR": "Other"})
    assert fleet[0].airline_name == "American Airlines"
    assert fleet[1].airline_name == "Ryanair"
