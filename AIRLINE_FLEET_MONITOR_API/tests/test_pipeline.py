"""Unit tests for the AFM pipeline orchestration (mocked client + sink)."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))

from AIRLINE_FLEET_MONITOR_API.config import AFMConfig
from AIRLINE_FLEET_MONITOR_API.pipeline import (
    TAB_FLEETS,
    TAB_LOG,
    TAB_QUALITY,
    FleetMonitorPipeline,
)

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_airlines.json")


class FakeClient:
    def __init__(self, raw):
        self._raw = raw

    def get_airlines_export(self):
        return self._raw

    def get_airline(self, slug):
        from AIRLINE_FLEET_MONITOR_API.models import AirlineFleet
        for rec in self._raw:
            if rec["slug"] == slug:
                return AirlineFleet.from_export_dict(rec)
        raise ValueError(f"unknown slug {slug}")


class FakeSink:
    def __init__(self):
        self.spreadsheet_id = "test-sheet-id"
        self.snapshots = {}
        self.appended = {}

    def write_snapshot(self, tab_name, headers, rows):
        self.snapshots[tab_name] = {"headers": list(headers), "rows": list(rows)}
        return len(rows)

    def append_rows(self, tab_name, headers, rows):
        self.appended.setdefault(tab_name, []).extend(rows)
        return len(rows)


def _sample():
    with open(SAMPLE_PATH) as fh:
        return json.load(fh)


def test_run_export_writes_three_tabs():
    sink = FakeSink()
    pipeline = FleetMonitorPipeline(client=FakeClient(_sample()), sink=sink,
                                    config=AFMConfig())
    result = pipeline.run_export()
    assert result.errors == []
    assert result.fetched == 5
    assert result.airlines_written == 4  # defunct excluded
    assert result.total_airframes == 1388 + 1239 + 0 + 145
    assert TAB_FLEETS in sink.snapshots
    assert sink.snapshots[TAB_FLEETS]["headers"][0] == "airline"
    assert len(sink.snapshots[TAB_FLEETS]["rows"]) == 4
    assert TAB_QUALITY in sink.snapshots
    assert len(sink.snapshots[TAB_QUALITY]["rows"]) > 5
    assert TAB_LOG in sink.appended
    assert sink.appended[TAB_LOG][0][5] == "OK"  # status column


def test_run_export_dry_run_writes_nothing():
    sink = FakeSink()
    pipeline = FleetMonitorPipeline(client=FakeClient(_sample()), sink=sink,
                                    config=AFMConfig())
    result = pipeline.run_export(write=False)
    assert result.errors == []
    assert result.airlines_written == 4
    assert sink.snapshots == {} and sink.appended == {}


def test_run_export_failure_reports_error_and_logs():
    class BrokenClient:
        def get_airlines_export(self):
            raise RuntimeError("boom")

    sink = FakeSink()
    pipeline = FleetMonitorPipeline(client=BrokenClient(), sink=sink,
                                    config=AFMConfig())
    result = pipeline.run_export()
    assert result.errors and "boom" in result.errors[0]
    assert result.airlines_written == 0
    assert TAB_LOG in sink.appended
    assert sink.appended[TAB_LOG][0][5] == "FAILED"


def test_run_airline_spot_check():
    pipeline = FleetMonitorPipeline(client=FakeClient(_sample()), sink=FakeSink(),
                                    config=AFMConfig())
    fleet = pipeline.run_airline("delta-air-lines")
    assert fleet.airline == "Delta Air Lines"
    assert fleet.total == 1388
    assert fleet.fetched_at != ""
