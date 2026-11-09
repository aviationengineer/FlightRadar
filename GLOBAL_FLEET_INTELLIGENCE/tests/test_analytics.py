"""Analytics (GA4) tests for the Global Airline Fleet Intelligence app:
off by default, snippet content, ID validation, secrets precedence,
once-per-session loader and page-change events.

Run:  python -m pytest tests/test_analytics.py -v
The pure helpers are exercised with a stubbed ``streamlit`` module so no
Streamlit runtime is needed; one AppTest check boots the real app and
asserts it runs clean with tracking off (no Measurement ID configured).
"""

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import analytics  # noqa: E402
from analytics import (  # noqa: E402
    event_snippet,
    inject_analytics,
    is_valid_measurement_id,
    loader_snippet,
    resolve_measurement_id,
)

APP = str(APP_DIR / "app.py")
VALID_ID = "G-ABC1234567"


class _FakeStreamlit:
    """Minimal stand-in for the streamlit module used by analytics.py."""

    def __init__(self, secrets=None):
        self.secrets = dict(secrets or {})
        self.session_state = {}
        self.html_calls: list = []


@pytest.fixture
def fake_st(monkeypatch):
    """Stub analytics.st and the components html import with recorders."""
    fake = _FakeStreamlit()

    def _html(content, height=0):
        fake.html_calls.append(content)

    monkeypatch.setattr(analytics, "st", fake)
    monkeypatch.setattr(analytics, "_get_components_html", lambda: _html)
    return fake


def test_config_default_is_empty():
    """No Measurement ID is committed anywhere; tracking is off by default."""
    assert analytics.GA_MEASUREMENT_ID == ""


def test_valid_and_invalid_ids():
    assert is_valid_measurement_id("G-ABC1234567")
    assert is_valid_measurement_id("G-1234ABCD")
    assert not is_valid_measurement_id("")
    assert not is_valid_measurement_id(None)
    assert not is_valid_measurement_id("UA-123456")
    assert not is_valid_measurement_id("G-")
    assert not is_valid_measurement_id("G-AB")
    assert not is_valid_measurement_id("G-ABC 123")
    assert not is_valid_measurement_id("https://example.com")


def test_no_id_means_no_tracking(fake_st):
    """No secrets, no config default: nothing resolves, nothing injects."""
    assert resolve_measurement_id() == ""
    assert loader_snippet("") == ""
    assert event_snippet("", "page_navigation", {"page_name": "Fuel"}) == ""
    assert inject_analytics() is False
    assert fake_st.html_calls == []


def test_invalid_id_is_ignored(fake_st):
    """An invalid ID (typo, UA- property, URL) disables tracking, no error."""
    fake_st.secrets = {"GA_MEASUREMENT_ID": "not-a-ga-id"}
    assert resolve_measurement_id() == ""
    assert loader_snippet("UA-123456") == ""
    assert inject_analytics() is False
    assert fake_st.html_calls == []


def test_secrets_take_precedence_over_config_default(fake_st):
    fake_st.secrets = {"GA_MEASUREMENT_ID": "G-SECRETS123"}
    assert resolve_measurement_id("G-CONFIG456") == "G-SECRETS123"
    fake_st.secrets = {}
    assert resolve_measurement_id("G-CONFIG456") == "G-CONFIG456"
    assert resolve_measurement_id() == ""


def test_loader_snippet_contains_id_and_gtag_config():
    snippet = loader_snippet(VALID_ID)
    assert VALID_ID in snippet
    assert "googletagmanager.com/gtag/js" in snippet
    assert "gtag('config'" in snippet
    assert "gtag('js'" in snippet
    # No other ID sneaks in.
    assert snippet.count("G-") == 1


def test_event_snippet_contains_event_and_page():
    # The event fires through the gtag configured by the loader, so the
    # snippet itself carries no Measurement ID — only the event + params.
    snippet = event_snippet(VALID_ID, "page_navigation",
                            {"page_name": "2 · Fleet Composition"})
    assert "page_navigation" in snippet
    assert "Fleet Composition" in snippet
    assert "G-" not in snippet
    assert event_snippet("bad-id", "page_navigation",
                         {"page_name": "Fuel"}) == ""


def test_inject_once_then_navigation_event(fake_st):
    """Loader fires once per session; a page change fires one event."""
    fake_st.secrets = {"GA_MEASUREMENT_ID": VALID_ID}

    assert inject_analytics(
        page_name="1 · Executive Overview") is True
    assert len(fake_st.html_calls) == 1
    assert "gtag('config'" in fake_st.html_calls[0]

    # Same page again: no duplicate injection.
    assert inject_analytics(
        page_name="1 · Executive Overview") is True
    assert len(fake_st.html_calls) == 1

    # Page change: exactly one navigation event, with the new page name.
    assert inject_analytics(
        page_name="2 · Fleet Composition") is True
    assert len(fake_st.html_calls) == 2
    assert "page_navigation" in fake_st.html_calls[1]
    assert "Fleet Composition" in fake_st.html_calls[1]


def test_inject_without_streamlit_returns_false(monkeypatch):
    """No Streamlit runtime at all: resolve still works, inject is a no-op."""
    monkeypatch.setattr(analytics, "st", None)
    assert resolve_measurement_id("G-CONFIG456") == "G-CONFIG456"
    assert inject_analytics(config_default="G-CONFIG456") is False


def test_app_boots_clean_with_tracking_off():
    """The real app runs with no Measurement ID configured: no exception."""
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, f"app raised: {at.exception}"
