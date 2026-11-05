"""Unit tests for the AFM client (mocked HTTP — no live key, no network)."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.expanduser("~/workspace"))

from AIRLINE_FLEET_MONITOR_API.afm_client import AFMAPIError, AirlineFleetMonitorClient
from AIRLINE_FLEET_MONITOR_API.config import AFMConfig

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_airlines.json")


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Minimal requests.Session stand-in: maps URL -> FakeResponse."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, timeout=None, **kwargs):
        self.calls.append(url)
        if url in self.mapping:
            return self.mapping[url]
        return FakeResponse({"error": "not found"}, status_code=404)


def _client(mapping):
    return AirlineFleetMonitorClient(AFMConfig(), session=FakeSession(mapping))


def _sample_export():
    with open(SAMPLE_PATH) as fh:
        return json.load(fh)


def test_export_returns_list_of_dicts():
    client = _client({AFMConfig().export_url: FakeResponse(_sample_export())})
    rows = client.get_airlines_export()
    assert isinstance(rows, list)
    assert len(rows) == 5
    assert rows[0]["name"] == "Delta Air Lines"


def test_export_non_list_raises():
    client = _client({AFMConfig().export_url: FakeResponse({"oops": True})})
    with pytest.raises(AFMAPIError, match="expected a JSON list"):
        client.get_airlines_export()


def test_export_fleets_parses_models():
    client = _client({AFMConfig().export_url: FakeResponse(_sample_export())})
    fleets = client.get_airlines_export_fleets(fetched_at="2026-11-05T00:00:00+00:00")
    assert fleets[0].airline == "Delta Air Lines"
    assert fleets[0].total == 1388
    assert fleets[0].fetched_at.startswith("2026-11-05")


def test_get_airline_unwraps_success_envelope():
    payload = {"success": True, "data": _sample_export()[0]}
    client = _client({"https://airlinefleetmonitor.com/api/v1/airlines/delta-air-lines":
                      FakeResponse(payload)})
    fleet = client.get_airline("delta-air-lines")
    assert fleet.airline == "Delta Air Lines"
    assert fleet.iata == "DL" and fleet.icao == "DAL"
    assert fleet.active == 1388


def test_get_airline_404_raises():
    client = _client({})
    with pytest.raises(AFMAPIError, match="404"):
        client.get_airline("no-such-airline")


def test_rate_limit_retried_then_raises():
    # 429 twice then success would need state; here always-429 exhausts retries.
    session = FakeSession({AFMConfig().export_url: FakeResponse({"e": 1}, status_code=429)})
    client = AirlineFleetMonitorClient(
        AFMConfig(max_retries=2), session=session)
    with pytest.raises(AFMAPIError, match="429"):
        client.get_airlines_export()
    assert len(session.calls) == 2


def test_get_aircraft_type_returns_data():
    payload = {"status": "success", "data": {"slug": "a359", "name": "Airbus A350-900",
                                              "observed_fleet_count": 578, "active_count": 552}}
    client = _client({"https://airlinefleetmonitor.com/api/v1/aircraft/a359":
                      FakeResponse(payload)})
    data = client.get_aircraft_type("a359")
    assert data["icao_type"] if "icao_type" in data else data["name"] == "Airbus A350-900"
    assert data["observed_fleet_count"] == 578


def test_get_deliveries_returns_data():
    payload = {"success": True, "data": {"total": 1, "deliveries": [{"reg": "N842DN"}]}}
    client = _client({"https://airlinefleetmonitor.com/api/v1/deliveries":
                      FakeResponse(payload)})
    data = client.get_deliveries()
    assert data["total"] == 1
