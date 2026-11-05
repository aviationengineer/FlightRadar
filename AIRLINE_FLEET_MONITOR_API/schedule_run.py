"""Scheduled runner: weekly AFM fleet snapshot into the Fleet Intelligence sheet.

Used by cron. Reads config from environment; no API key is needed.
Set GOOGLE_SHEET_ID to override the default workbook.

Example cron (weekly, Monday 07:00 America/Edmonton):
    0 7 * * 1 /usr/bin/python3 ~/workspace/AIRLINE_FLEET_MONITOR_API/schedule_run.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

os.environ.setdefault("GOOGLE_SHEET_ID", "1cTgndcs_1egjtc8ND5cZvjrQPjHLpZeRIllnQTLBKHo")

from AIRLINE_FLEET_MONITOR_API.pipeline import FleetMonitorPipeline  # noqa: E402
from LIB.logging_utils import get_logger  # noqa: E402

log = get_logger("afm-schedule")


def main() -> None:
    pipeline = FleetMonitorPipeline()
    result = pipeline.run_export()
    if result.errors:
        log.error("Scheduled AFM run failed: %s", result.errors)
        sys.exit(1)
    log.info(
        "Scheduled AFM run OK: fetched=%d airlines_written=%d total_airframes=%d "
        "quality=%s sheet=%s",
        result.fetched, result.airlines_written, result.total_airframes,
        result.quality, result.spreadsheet_id,
    )


if __name__ == "__main__":
    main()
