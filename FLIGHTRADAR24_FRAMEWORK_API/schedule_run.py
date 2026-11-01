"""Scheduled runner: ingest FR24 live flights into the Quick Schedule sheet.

Used by cron. Reads config from environment.
Set FR24_API_TOKEN, GOOGLE_SHEET_ID, GOOGLE_SHEET_TAB.

Example cron (every 15 min):
    */15 * * * * /usr/bin/python3 ~/workspace/FLIGHTRADAR24_FRAMEWORK_API/schedule_run.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

# Defaults for the quick schedule sheet
os.environ.setdefault("GOOGLE_SHEET_ID", "1pg-7JoJZvWeq_Ra5YaQbJI2nOnZSNYQbrf43vKkWY0E")
os.environ.setdefault("GOOGLE_SHEET_TAB", "Sheet1")

from LIB.logging_utils import get_logger
from pipeline import FlightIngestionPipeline

log = get_logger("fr24-schedule")

# Default bounds: London Heathrow area – override via FR24_BOUNDS env
DEFAULT_BOUNDS = os.getenv("FR24_BOUNDS", "51.6,51.4,-0.6,-0.3")
DEFAULT_LIMIT = int(os.getenv("FR24_LIMIT", "50"))


def main() -> None:
    if not os.getenv("FR24_API_TOKEN"):
        log.error("FR24_API_TOKEN not set – skipping scheduled run")
        sys.exit(1)
    pipeline = FlightIngestionPipeline()
    # Ensure sink points at quick sheet
    pipeline.sink.spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    pipeline.sink.tab_name = os.getenv("GOOGLE_SHEET_TAB", "Sheet1")
    result = pipeline.run_live(bounds=DEFAULT_BOUNDS, limit=DEFAULT_LIMIT, create_sheet_if_needed=False)
    if result.errors:
        log.error("Scheduled run failed: %s", result.errors)
        sys.exit(1)
    log.info("Scheduled run OK: fetched=%d written=%d sheet=%s", result.fetched, result.written, result.spreadsheet_id)


if __name__ == "__main__":
    main()
