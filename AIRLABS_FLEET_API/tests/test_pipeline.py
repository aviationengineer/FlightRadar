"""Unit tests for the pipeline: quota guard, disk cache, weekly rotation,
sheet writes (fake sink), and the missing-key path. No network, no key.
"""

import json

import pytest

from AIRLABS_FLEET_API.config import (
    TAB_CATALOG, TAB_FLEETS, TAB_LOG, TAB_QUALITY, AirlabsConfig,
)
from AIRLABS_FLEET_API.models import FleetAircraft
from AIRLABS_FLEET_API.pipeline import AirlabsFleetPipeline
from AIRLABS_FLEET_API.transforms import aircraft_to_rows


def _ac(hex_code="A9D286", reg="N732AN", iata="AA", **overrides):
    kwargs = {"hex": hex_code, "reg_number": reg, "airline_icao": "AAL",
              "airline_iata": iata, "icao_type": "77W",
              "model": "Boeing 777-300ER pax", "manufacturer": "BOEING",
              "age": 11, "fetched_at": "2026-11-05T00:00:00+00:00"}
    kwargs.update(overrides)
    return FleetAircraft(**kwargs)


class FakeClient:
    """Stand-in for AirlabsClient with canned data + call counts."""

    def __init__(self, full=None, by_airline=None, names=None):
        self.full = full if full is not None else [_ac(), _ac("BBBBBB", "N111AA")]
        self.by_airline = by_airline or {}
        self.names = names if names is not None else {"AA": "American Airlines"}
        self.request_count = 0
        self.full_calls = 0
        self.airline_calls = []

    def get_all_fleets(self, max_pages=None):
        self.full_calls += 1
        self.request_count += 3  # pretend 3 paged requests
        return list(self.full)

    def get_airline_fleets(self, iata=None, icao=None, max_pages=None):
        self.airline_calls.append(iata)
        self.request_count += 1
        return list(self.by_airline.get(iata, [_ac(iata=iata)]))

    def get_airline_names(self, max_pages=None):
        self.request_count += 1
        return dict(self.names)


class FakeSink:
    """In-memory stand-in for AirlabsSheetsSink."""

    def __init__(self):
        self.spreadsheet_id = "test-sheet-id"
        self.tables = {}   # tab -> (headers, rows)
        self.appended = {}  # tab -> [rows]
        self.existing = {}  # tab -> rows returned by read_table

    def write_table(self, tab, headers, rows, replace=True):
        self.tables[tab] = (list(headers), [list(r) for r in rows])
        return len(rows)

    def append_rows(self, tab, rows, headers=None):
        self.appended.setdefault(tab, []).extend([list(r) for r in rows])
        return len(rows)

    def read_table(self, tab, max_rows=None):
        return self.existing.get(tab, [])


def _pipeline(tmp_path, client=None, sink=None, **config_overrides):
    cfg = AirlabsConfig(
        api_key="test-key",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
        **config_overrides)
    return AirlabsFleetPipeline(config=cfg, client=client or FakeClient(),
                                sink=sink or FakeSink())


def test_full_refresh_writes_all_four_tabs(tmp_path):
    pipe = _pipeline(tmp_path)
    result = pipe.run_full_refresh()
    assert result.status == "ok"
    assert result.fetched == 2 and result.written == 2
    assert result.requests_made == 3
    assert TAB_FLEETS in pipe.sink.tables
    assert TAB_QUALITY in pipe.sink.tables
    assert TAB_CATALOG in pipe.sink.tables
    assert TAB_LOG in pipe.sink.appended
    headers, rows = pipe.sink.tables[TAB_FLEETS]
    assert headers[0] == "hex" and rows[0][1] == "N732AN"
    assert rows[0][4] == "American Airlines"  # enriched from /airlines
    catalog_headers, catalog_rows = pipe.sink.tables[TAB_CATALOG]
    assert catalog_rows[0][0] == "AirLabs"
    assert "900" in str(catalog_rows[0][4])  # quota budget recorded


def test_full_refresh_second_run_is_cache_hit_zero_requests(tmp_path):
    pipe = _pipeline(tmp_path)
    first = pipe.run_full_refresh()
    assert first.cache_hit is False
    calls_after_first = pipe.client.full_calls
    second = pipe.run_full_refresh()
    assert second.cache_hit is True
    assert second.requests_made == 0
    assert pipe.client.full_calls == calls_after_first  # no new API calls


def test_quota_guard_skips_full_pull(tmp_path):
    pipe = _pipeline(tmp_path)
    state = pipe.quota.path
    import datetime
    state.write_text(json.dumps(
        {"month": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m"),
         "requests": 900}))
    result = pipe.run_full_refresh()
    assert result.status == "skipped_quota"
    assert pipe.client.full_calls == 0
    assert "soft cap" in result.errors[0]


def test_weekly_slice_is_ten_top_airlines(tmp_path):
    pipe = _pipeline(tmp_path)
    slice_ = pipe._weekly_slice()
    assert len(slice_) == 10
    assert set(slice_) <= set(pipe.config.top_airlines)
    assert len(pipe.config.top_airlines) == 50


def test_weekly_refresh_merges_into_existing_sheet(tmp_path):
    sink = FakeSink()
    sink.existing[TAB_FLEETS] = (
        [FleetAircraft.sheet_headers()]
        + aircraft_to_rows([_ac(), _ac("BBBBBB", "N111AA")]))
    client = FakeClient(by_airline={"AA": [_ac(model="Boeing 777 updated")]})
    pipe = _pipeline(tmp_path, client=client, sink=sink)
    # Force the weekly slice to just AA for a deterministic test.
    pipe.config = AirlabsConfig(
        api_key="test-key", cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state", top_airlines=["AA"],
        weekly_slice_size=1)
    result = pipe.run_weekly_refresh()
    assert result.status == "ok"
    _, rows = sink.tables[TAB_FLEETS]
    assert len(rows) == 2  # updated in place, not duplicated
    assert rows[0][6] == "Boeing 777 updated"


def test_rate_limit_error_is_reported_not_raised(tmp_path):
    class LimitClient(FakeClient):
        def get_all_fleets(self, max_pages=None):
            from AIRLABS_FLEET_API.airlabs_client import AirlabsRateLimitError
            raise AirlabsRateLimitError("month limit", limit_kind="month")

    pipe = _pipeline(tmp_path, client=LimitClient())
    result = pipe.run_full_refresh()
    assert result.status == "rate_limited"
    assert "month" in result.errors[0]


def test_missing_key_blocks_pipeline_construction(monkeypatch):
    monkeypatch.delenv("AIRLABS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AIRLABS_API_KEY is not set"):
        AirlabsFleetPipeline()
