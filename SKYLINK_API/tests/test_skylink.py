"""Unit tests for the Skylink pipeline — mocked HTTP, no live key needed."""

import os
import sys

import pytest

sys.path.insert(0, os.path.expanduser("~/workspace"))

from SKYLINK_API.config import MISSING_KEY_MESSAGE, SkylinkConfig
from SKYLINK_API.models import AircraftObservation
from SKYLINK_API.pipeline import SkylinkIngestionPipeline
from SKYLINK_API.sheets_sink import SkylinkSheetsSink
from SKYLINK_API.skylink_client import SkylinkClient
from SKYLINK_API.transforms import (
    dedupe_by_icao24,
    normalize_observations,
    normalize_registration,
    run_quality_checks,
    summarize_by_airline,
)


# ----------------------------------------------------------------------
# fakes
# ----------------------------------------------------------------------
class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}
        self.text = str(payload)[:500]

    def json(self):
        return self._payload


class FakeSession:
    """requests.Session stand-in: serves canned payloads in order."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def request(self, method, url, headers=None, params=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "headers": headers})
        payload = self.payloads.pop(0) if self.payloads else {"data": []}
        if isinstance(payload, FakeResponse):
            return payload
        return FakeResponse(payload)


def _config(**overrides):
    kwargs = {"api_key": "test-key", "page_size": 2, "max_pages_per_airline": 5}
    kwargs.update(overrides)
    return SkylinkConfig(**kwargs)


def _obs(**overrides):
    base = {
        "icao24": "abc123",
        "registration": "C-FRSR",
        "callsign": "ACA101",
        "airline_name": "Air Canada",
        "airline_icao": "ACA",
        "aircraft_type": "B789",
        "model": "787-9",
        "manufacturer": "Boeing",
        "operator": "Air Canada",
        "observed_at": "2026-11-05T12:00:00Z",
    }
    base.update(overrides)
    return AircraftObservation(**base)


# ----------------------------------------------------------------------
# config / missing-key path
# ----------------------------------------------------------------------
def test_from_env_raises_with_clear_message_when_key_missing(monkeypatch):
    monkeypatch.delenv("SKYLINK_RAPIDAPI_KEY", raising=False)
    with pytest.raises(ValueError, match="SKYLINK_RAPIDAPI_KEY is not set"):
        SkylinkConfig.from_env()


def test_from_env_or_none_returns_none_when_key_missing(monkeypatch):
    monkeypatch.delenv("SKYLINK_RAPIDAPI_KEY", raising=False)
    assert SkylinkConfig.from_env_or_none() is None


def test_from_env_reads_key_and_airlines(monkeypatch):
    monkeypatch.setenv("SKYLINK_RAPIDAPI_KEY", "  my-key  ")
    monkeypatch.setenv("SKYLINK_AIRLINES", "Air Canada, WestJet")
    cfg = SkylinkConfig.from_env()
    assert cfg.api_key == "my-key"
    assert cfg.target_airlines == ("Air Canada", "WestJet")


def test_schedule_run_skips_gracefully_without_key(monkeypatch):
    monkeypatch.delenv("SKYLINK_RAPIDAPI_KEY", raising=False)
    import SKYLINK_API.schedule_run as sched
    assert sched.main() == 0  # exit 0, never an error


def test_missing_key_message_names_rapidapi():
    assert "RapidAPI" in MISSING_KEY_MESSAGE
    assert "SKYLINK_RAPIDAPI_KEY" in MISSING_KEY_MESSAGE


# ----------------------------------------------------------------------
# client: headers, pagination, endpoints
# ----------------------------------------------------------------------
def test_client_sends_rapidapi_headers():
    session = FakeSession([{"data": []}])
    client = SkylinkClient(_config(), session=session)
    client.get_adsb_aircraft(airline="Air Canada")
    headers = session.calls[0]["headers"]
    assert headers["X-RapidAPI-Key"] == "test-key"
    assert headers["X-RapidAPI-Host"] == "skylink-api.p.rapidapi.com"


def test_client_pagination_follows_pages_until_short_page():
    page1 = {"data": [
        {"icao24": "a1", "registration": "C-AAAA", "callsign": "ACA1"},
        {"icao24": "a2", "registration": "C-BBBB", "callsign": "ACA2"},
    ]}
    page2 = {"data": [
        {"icao24": "a3", "registration": "C-CCCC", "callsign": "ACA3"},
    ]}
    session = FakeSession([page1, page2])
    client = SkylinkClient(_config(), session=session)
    obs = client.get_adsb_aircraft(airline="Air Canada")
    assert [o.icao24 for o in obs] == ["a1", "a2", "a3"]
    assert len(session.calls) == 2
    assert client.adsb_requests == 2
    assert session.calls[1]["params"]["page"] == 2


def test_client_pagination_stops_at_max_pages():
    full_page = {"data": [
        {"icao24": "x1", "registration": "C-AAAA"},
        {"icao24": "x2", "registration": "C-BBBB"},
    ]}
    session = FakeSession([full_page] * 10)
    client = SkylinkClient(_config(max_pages_per_airline=3), session=session)
    obs = client.get_adsb_aircraft(airline="Air Canada")
    assert len(session.calls) == 3
    assert len(obs) == 6


def test_client_applies_limit():
    page = {"data": [
        {"icao24": "a1", "registration": "C-AAAA"},
        {"icao24": "a2", "registration": "C-BBBB"},
    ]}
    session = FakeSession([page])
    client = SkylinkClient(_config(), session=session)
    obs = client.get_adsb_aircraft(airline="Air Canada", limit=1)
    assert len(obs) == 1


def test_client_handles_bare_list_envelope():
    session = FakeSession([[{"icao24": "z9", "registration": "C-ZZZZ"}]])
    client = SkylinkClient(_config(), session=session)
    obs = client.get_adsb_aircraft()
    assert len(obs) == 1 and obs[0].icao24 == "z9"


def test_client_401_raises():
    session = FakeSession([FakeResponse({"message": "forbidden"}, status_code=401)])
    client = SkylinkClient(_config(), session=session)
    with pytest.raises(Exception, match="401"):
        client.get_adsb_aircraft()


def test_registration_lookup():
    payload = {"data": {
        "registration": "C-FRSR", "manufacturer": "Boeing",
        "model": "787-9", "operator": "Air Canada",
    }}
    session = FakeSession([payload])
    client = SkylinkClient(_config(), session=session)
    detail = client.get_aircraft_by_registration("c-frsr")
    assert detail.operator == "Air Canada"
    assert detail.model == "787-9"
    assert client.registration_lookups == 1
    assert "c-frsr".upper() in session.calls[0]["url"]


def test_search_airline_rejects_both_codes():
    client = SkylinkClient(_config(), session=FakeSession([]))
    with pytest.raises(ValueError, match="never both"):
        client.search_airline(icao="ACA", iata="AC")


def test_search_airline_requires_one_code():
    client = SkylinkClient(_config(), session=FakeSession([]))
    with pytest.raises(ValueError):
        client.search_airline()


def test_search_airline_by_icao():
    session = FakeSession([{"data": [
        {"name": "Air Canada", "icao": "ACA", "iata": "AC", "country": "Canada"},
    ]}])
    client = SkylinkClient(_config(), session=session)
    airlines = client.search_airline(icao="ACA")
    assert len(airlines) == 1 and airlines[0].name == "Air Canada"
    assert session.calls[0]["params"] == {"icao": "ACA"}


# ----------------------------------------------------------------------
# transforms / normalisation
# ----------------------------------------------------------------------
def test_normalize_registration_strips_dash_and_uppercases():
    assert normalize_registration("c-frsr") == "CFRSR"
    assert normalize_registration(" C-FRSR ") == "CFRSR"


def test_normalize_observations_fills_operator_and_timestamp():
    obs = normalize_observations([_obs(operator="", observed_at="")])
    assert obs[0].operator == "Air Canada"
    assert obs[0].registration == "CFRSR"
    assert obs[0].observed_at  # stamped


def test_dedupe_by_icao24_keeps_first():
    a = _obs(icao24="abc123", callsign="ACA101")
    b = _obs(icao24="abc123", callsign="ACA102")
    c = _obs(icao24="def456", callsign="ACA103")
    out = dedupe_by_icao24([a, b, c])
    assert [o.callsign for o in out] == ["ACA101", "ACA103"]


def test_summarize_by_airline_counts_and_types():
    obs = [
        _obs(icao24="a1", airline_name="Air Canada", aircraft_type="B789"),
        _obs(icao24="a2", airline_name="Air Canada", aircraft_type="B789"),
        _obs(icao24="a3", airline_name="WestJet", aircraft_type="B738"),
    ]
    summary = summarize_by_airline(obs)
    assert summary[0]["airline_name"] == "Air Canada"
    assert summary[0]["aircraft_observed"] == 2
    assert "B789 x2" in summary[0]["aircraft_types"]


def test_quality_checks_flag_missing_airline():
    obs = [_obs(), _obs(icao24="x2", airline_name="", operator="", airline_icao="")]
    rows = run_quality_checks(obs)
    by_name = {r.check_name: r for r in rows}
    assert by_name["airline_resolved"].failed_rows == 1
    assert by_name["airline_resolved"].pass_rate_pct == 50.0
    assert by_name["airline_resolved"].status == "FAIL"
    assert by_name["registration_present"].status == "PASS"
    assert by_name["icao24_unique"].failed_rows == 0


def test_observation_sheet_row_matches_headers():
    obs = _obs()
    assert len(obs.to_sheet_row()) == len(AircraftObservation.sheet_headers())
    assert obs.to_sheet_row()[1] == "C-FRSR"


# ----------------------------------------------------------------------
# sheets sink: chunking
# ----------------------------------------------------------------------
def test_chunk_rows_splits_large_payloads():
    rows = [["x" * 500, "y"] for _ in range(10)]
    chunks = SkylinkSheetsSink.chunk_rows(rows, max_json_bytes=1200)
    assert len(chunks) > 1
    assert sum(len(c) for c in chunks) == 10
    for chunk in chunks:
        import json as _json
        assert len(_json.dumps(chunk).encode()) <= 1200 + 600  # one row may exceed


def test_chunk_rows_single_small_batch():
    rows = [["a", "b"], ["c", "d"]]
    assert SkylinkSheetsSink.chunk_rows(rows) == [rows]


# ----------------------------------------------------------------------
# pipeline (mocked client + fake sink — no network, no Sheets CLI)
# ----------------------------------------------------------------------
class FakeClient:
    def __init__(self, per_airline):
        self.per_airline = per_airline
        self.adsb_requests = 0
        self.registration_lookups = 0
        self.lookups = []

    def get_adsb_aircraft(self, airline=None, limit=None):
        self.adsb_requests += 1
        rows = list(self.per_airline.get(airline, []))
        return rows[:limit] if limit else rows

    def get_aircraft_by_registration(self, registration):
        self.registration_lookups += 1
        self.lookups.append(registration)
        from SKYLINK_API.models import RegistrationDetail
        return RegistrationDetail(
            registration=registration, operator="Air Canada",
            manufacturer="Boeing", model="787-9",
        )


class FakeSink:
    def __init__(self):
        self.spreadsheet_id = "sheet-123"
        self.written = {}

    def append_rows_to_tab(self, tab_name, headers, rows):
        self.written.setdefault(tab_name, []).extend(rows)
        return len(rows)


def test_pipeline_snapshot_writes_fleets_quality_log():
    per_airline = {
        "Air Canada": [_obs(icao24="a1"), _obs(icao24="a1", callsign="ACA999")],
        "WestJet": [_obs(icao24="w1", airline_name="", operator="",
                         airline_icao="", registration="C-GWJO",
                         callsign="WJA1", aircraft_type="B738")],
    }
    pipeline = SkylinkIngestionPipeline(
        client=FakeClient(per_airline), sink=FakeSink(), config=_config(),
    )
    result = pipeline.run_weekly_snapshot(airlines=["Air Canada", "WestJet"])
    assert result.errors == []
    assert result.fetched == 3
    assert result.deduped == 2  # duplicate a1 removed
    assert result.written == 2
    assert result.adsb_requests == 2
    assert result.registration_lookups == 1  # only the unresolved WestJet row
    assert "SKYLINK_Fleets" in pipeline.sink.written
    assert len(pipeline.sink.written["SKYLINK_Fleets"]) == 2
    assert "SKYLINK_Data_Quality" in pipeline.sink.written
    assert "SKYLINK_Ingestion_Log" in pipeline.sink.written
    log_row = pipeline.sink.written["SKYLINK_Ingestion_Log"][0]
    assert log_row[8] == "OK"  # status column


def test_pipeline_enrichment_respects_lookup_cap():
    unresolved = [
        _obs(icao24=f"u{i}", registration=f"C-U00{i}", airline_name="",
             operator="", airline_icao="", callsign=f"UNK{i}")
        for i in range(5)
    ]
    pipeline = SkylinkIngestionPipeline(
        client=FakeClient({"Air Canada": unresolved}),
        sink=FakeSink(), config=_config(max_registration_lookups=2),
    )
    result = pipeline.run_weekly_snapshot(airlines=["Air Canada"])
    assert result.registration_lookups == 2
    assert result.operators_resolved == 2


def test_pipeline_failure_is_reported_not_raised():
    class FailingClient(FakeClient):
        def get_adsb_aircraft(self, airline=None, limit=None):
            raise RuntimeError("boom")

    pipeline = SkylinkIngestionPipeline(
        client=FailingClient({}), sink=FakeSink(), config=_config(),
    )
    result = pipeline.run_weekly_snapshot(airlines=["Air Canada"])
    assert result.errors and "boom" in result.errors[0]
    assert result.written == 0
