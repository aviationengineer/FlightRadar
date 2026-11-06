"""Headless tests for the Global Airline Fleet Intelligence dashboard.

Run:  python -m pytest tests/test_app.py -v
Uses streamlit.testing.v1.AppTest. The app must render every page with zero
exceptions, show the verified headline KPIs, and render the N/A placeholders
for every KPI that has no source.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"
PAGES = [
    "1 · Executive Overview", "2 · Fleet Composition",
    "3 · Fleet Age & Replacement", "4 · Future Fleet & Order Book",
    "5 · Competitive Benchmark", "6 · Data Quality & Sources",
]


def run_page(page):
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception, f"overview run raised: {at.exception}"
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, f"{page} raised: {at.exception}"
    return at


def test_all_pages_render():
    for page in PAGES:
        run_page(page)


def test_headline_kpis():
    at = run_page("1 · Executive Overview")
    text = at.markdown[0].value if at.markdown else ""
    # KPI cards are rendered as markdown HTML; check the values appear.
    joined = " ".join(m.value for m in at.markdown)
    assert "25,226" in joined, "AFM total fleet KPI missing"
    assert "41,752" in joined, "OpenSky registered fleet KPI missing"
    assert "10.8" in joined, "AirLabs avg age KPI missing"


def test_na_placeholders_present():
    at = run_page("1 · Executive Overview")
    joined = " ".join(m.value for m in at.markdown)
    assert "N/A" in joined
    assert "Data unavailable" in joined
    at4 = run_page("4 · Future Fleet & Order Book")
    joined4 = " ".join(m.value for m in at4.markdown)
    assert "N/A — Data unavailable" in joined4
    assert "FACT_AIRCRAFT_ORDER is empty by design" in joined4


def test_kpi_layer():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import kpis
    model = kpis.load_model()
    assert kpis.total_fleet_afm(model["dim"]) == 25226
    assert kpis.registered_fleet_opensky(model["dim"]) == 41752
    assert kpis.order_book() is None
    assert kpis.fleet_growth_yoy() is None
    assert kpis.fleet_cagr() is None
    assert kpis.fleet_utilization() is None
    assert kpis.flag_age(8.0) == "GREEN"
    assert kpis.flag_age(12.0) == "AMBER"
    assert kpis.flag_age(18.0) == "RED"
    assert kpis.flag_age(None) == "N/A"
    insights = kpis.generate_insights(model)
    assert len(insights) >= 5
    assert any("DAL" in i or "Delta" in i for i in insights)
