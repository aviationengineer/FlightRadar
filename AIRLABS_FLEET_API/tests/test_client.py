"""Unit tests for AirlabsClient — mocked HTTP, no live key needed."""

import pytest

from AIRLABS_FLEET_API.airlabs_client import (
    AirlabsClient,
    AirlabsRateLimitError,
)
from AIRLABS_FLEET_API.config import AirlabsConfig, MISSING_KEY_MESSAGE


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = str(self._payload)[:500]

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Stand-in for requests.Session; serves canned responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []  # (method, url, params)

    def request(self, method, url, headers=None, params=None, timeout=None):
        self.calls.append((method, url, dict(params or {})))
        if not self.responses:
            raise AssertionError("FakeSession ran out of responses")
        return self.responses.pop(0)


def _config(**overrides):
    kwargs = {"api_key": "test-key", "page_size": 2,
              "retry_delay_seconds": 0}
    kwargs.update(overrides)
    return AirlabsConfig(**kwargs)


def _fleet_record(hex_code="A9D286", reg="N732AN", iata="AA", icao="AAL"):
    return {"hex": hex_code, "reg_number": reg, "airline_iata": iata,
            "airline_icao": icao, "icao": "77W", "model": "Boeing 777-300ER pax",
            "manufacturer": "BOEING", "age": 11}


def _page(records):
    return {"request": {"key": {"api_key": "SHOULD-NEVER-BE-LOGGED"}},
            "response": records}


def test_pagination_walks_limit_offset_until_short_page():
    session = FakeSession([
        FakeResponse(200, _page([_fleet_record("AAAA01"), _fleet_record("AAAA02")])),
        FakeResponse(200, _page([_fleet_record("AAAA03")])),
    ])
    client = AirlabsClient(_config(), session=session, sleep=lambda s: None)
    aircraft = client.get_all_fleets()
    assert [a.hex for a in aircraft] == ["AAAA01", "AAAA02", "AAAA03"]
    assert client.request_count == 2
    # Auth travels as api_key query param; _fields keeps payloads small.
    _, _, params0 = session.calls[0]
    assert params0["api_key"] == "test-key"
    assert params0["limit"] == 2 and params0["offset"] == 0
    assert params0["_fields"]
    assert session.calls[1][2]["offset"] == 2


def test_airline_filter_params():
    session = FakeSession([FakeResponse(200, _page([_fleet_record()]))])
    client = AirlabsClient(_config(), session=session, sleep=lambda s: None)
    aircraft = client.get_airline_fleets(iata="aa")
    assert len(aircraft) == 1
    assert session.calls[0][2]["airline_iata"] == "AA"


def test_minute_limit_retries_once_then_succeeds():
    session = FakeSession([
        FakeResponse(200, {"error": {"code": "minute_limit_exceeded",
                                     "message": "too fast"}}),
        FakeResponse(200, _page([_fleet_record()])),
    ])
    client = AirlabsClient(_config(), session=session, sleep=lambda s: None)
    assert len(client.get_all_fleets()) == 1
    assert client.request_count == 2


def test_hour_limit_raises_with_kind():
    session = FakeSession([
        FakeResponse(200, {"error": {"code": "hour_limit_exceeded",
                                     "message": "hourly quota spent"}}),
    ])
    client = AirlabsClient(_config(), session=session, sleep=lambda s: None)
    with pytest.raises(AirlabsRateLimitError) as excinfo:
        client.get_all_fleets()
    assert excinfo.value.limit_kind == "hour"


def test_month_limit_raises_with_kind_and_no_retry():
    session = FakeSession([
        FakeResponse(200, {"error": {"code": "month_limit_exceeded",
                                     "message": "monthly quota spent"}}),
    ])
    client = AirlabsClient(_config(), session=session, sleep=lambda s: None)
    with pytest.raises(AirlabsRateLimitError) as excinfo:
        client.get_all_fleets()
    assert excinfo.value.limit_kind == "month"
    assert client.request_count == 1


def test_http_429_maps_to_rate_limit(monkeypatch):
    monkeypatch.setattr("LIB.http.time.sleep", lambda s: None)
    session = FakeSession([
        FakeResponse(429, {"error": "slow down"}, headers={"Retry-After": "0"}),
        FakeResponse(429, {"error": "slow down"}, headers={"Retry-After": "0"}),
        FakeResponse(429, {"error": "slow down"}, headers={"Retry-After": "0"}),
    ])
    client = AirlabsClient(_config(), session=session, sleep=lambda s: None)
    with pytest.raises(AirlabsRateLimitError) as excinfo:
        client.get_all_fleets()
    assert excinfo.value.limit_kind == "minute"


def test_airline_names_mapping():
    session = FakeSession([
        FakeResponse(200, {"response": [
            {"name": "American Airlines", "iata_code": "AA", "icao_code": "AAL"},
            {"name": "Ryanair", "iata_code": "FR", "icao_code": "RYR"},
        ]}),
        FakeResponse(200, {"response": []}),  # short page ends pagination
    ])
    client = AirlabsClient(_config(), session=session, sleep=lambda s: None)
    names = client.get_airline_names()
    assert names["AA"] == "American Airlines"
    assert names["RYR"] == "Ryanair"
    assert session.calls[0][2]["_fields"]


def test_missing_key_raises_clear_message(monkeypatch):
    monkeypatch.delenv("AIRLABS_API_KEY", raising=False)
    with pytest.raises(ValueError) as excinfo:
        AirlabsConfig.from_env()
    assert "airlabs.co" in str(excinfo.value)
    assert "AIRLABS_API_KEY" in str(excinfo.value)
    assert MISSING_KEY_MESSAGE in str(excinfo.value)


def test_page_size_clamped_for_free_keys(monkeypatch):
    monkeypatch.setenv("AIRLABS_API_KEY", "k")
    monkeypatch.setenv("AIRLABS_PAGE_SIZE", "500")
    assert AirlabsConfig.from_env().page_size == 500
    monkeypatch.setenv("AIRLABS_PAGE_SIZE", "9999")
    assert AirlabsConfig.from_env().page_size == 500
