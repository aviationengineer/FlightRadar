"""Tests for the weekly snapshot history (snapshot_weekly.py output).

Run:  python -m pytest tests/test_weekly.py -v
The baseline snapshot (2026-11-08) is the real model data; the two-snapshot
case is synthetic, in a temp dir, so the test never mutates the live model.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kpis  # noqa: E402


def test_baseline_history_loads():
    hist = kpis.load_weekly_history()
    assert hist["dates"] == ["2026-11-08"], "baseline snapshot date missing"
    assert hist["snapshots"] is not None
    assert len(hist["snapshots"]) == 864  # 860 AFM airlines + 4 ALL rows
    # Baseline has no changes file yet (nothing to compare against).
    assert hist["changes"] is None
    # Fewer than 2 snapshots -> no week-over-week summary.
    assert kpis.weekly_change_summary() is None


def test_insights_mention_weekly_history():
    model = kpis.load_model()
    insights = kpis.generate_insights(model)
    assert any("Weekly fleet history started 2026-11-08" in i
               for i in insights)
    # Honesty preserved: YoY / CAGR / orders / utilization still N/A.
    assert kpis.fleet_growth_yoy() is None
    assert kpis.fleet_cagr() is None
    assert kpis.order_book() is None
    assert kpis.fleet_utilization() is None


def test_two_snapshots_yield_deltas(tmp_path, monkeypatch):
    weekly = pd.DataFrame([
        {"snapshot_date": "2026-11-08", "source": "afm",
         "airline_id": "ALL", "fleet_count": 25226, "active_fleet": 25226},
        {"snapshot_date": "2026-11-08", "source": "afm",
         "airline_id": "DAL", "fleet_count": 1000, "active_fleet": 1000},
        {"snapshot_date": "2026-11-16", "source": "afm",
         "airline_id": "ALL", "fleet_count": 25230, "active_fleet": 25230},
        {"snapshot_date": "2026-11-16", "source": "afm",
         "airline_id": "DAL", "fleet_count": 1002, "active_fleet": 1002},
    ])
    changes = pd.DataFrame([
        {"snapshot_date": "2026-11-16", "source": "afm",
         "airline_id": "ALL", "metric": "total_aircraft",
         "previous_value": 25226, "current_value": 25230, "delta": 4,
         "delta_pct": 0.02},
        {"snapshot_date": "2026-11-16", "source": "afm",
         "airline_id": "DAL", "metric": "total_aircraft",
         "previous_value": 1000, "current_value": 1002, "delta": 2,
         "delta_pct": 0.2},
    ])
    weekly.to_csv(tmp_path / "FACT_FLEET_HISTORY_WEEKLY.csv", index=False)
    changes.to_csv(tmp_path / "WEEKLY_CHANGES.csv", index=False)
    monkeypatch.setattr(kpis, "MODEL", tmp_path)
    summary = kpis.weekly_change_summary()
    assert summary is not None
    assert summary["first_date"] == "2026-11-08"
    assert summary["latest_date"] == "2026-11-16"
    assert summary["previous_date"] == "2026-11-08"
    assert summary["n_snapshots"] == 2
    assert len(summary["changes"]) == 2
    dal = summary["changes"][summary["changes"]["airline_id"] == "DAL"].iloc[0]
    assert int(dal["delta"]) == 2


def test_no_history_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(kpis, "MODEL", tmp_path)
    hist = kpis.load_weekly_history()
    assert hist["dates"] == []
    assert kpis.weekly_change_summary() is None
