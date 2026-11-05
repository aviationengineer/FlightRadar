"""Scheduled runner: weekly Skylink ADS-B snapshot → Fleet Intelligence sheet.

Used by cron. Reads config from environment.
Set SKYLINK_RAPIDAPI_KEY (and optionally GOOGLE_SHEET_ID, SKYLINK_AIRLINES).

Missing key behaviour (by design): log + exit 0. A cron job must never
error loudly just because no free RapidAPI key has been set yet.

Recommended cron (weekly, Monday 07:00 America/Edmonton):
    0 7 * * 1 /usr/bin/python3 ~/workspace/SKYLINK_API/schedule_run.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from LIB.logging_utils import get_logger  # noqa: E402

from SKYLINK_API.config import MISSING_KEY_MESSAGE, SkylinkConfig  # noqa: E402
from SKYLINK_API.pipeline import (  # noqa: E402
    DEFAULT_SPREADSHEET_ID,
    SkylinkIngestionPipeline,
)

log = get_logger("skylink-schedule")

os.environ.setdefault("GOOGLE_SHEET_ID", DEFAULT_SPREADSHEET_ID)


def main() -> int:
    config = SkylinkConfig.from_env_or_none()
    if config is None:
        # Graceful skip: no key yet — not an error, never exit non-zero.
        log.warning("Skipping scheduled Skylink run: %s", MISSING_KEY_MESSAGE)
        return 0
    pipeline = SkylinkIngestionPipeline(config=config)
    result = pipeline.run_weekly_snapshot()
    if result.errors:
        log.error("Scheduled run failed: %s", result.errors)
        return 1
    log.info(
        "Scheduled run OK: fetched=%d written=%d adsb_requests=%d "
        "reg_lookups=%d sheet=%s",
        result.fetched, result.written, result.adsb_requests,
        result.registration_lookups, result.spreadsheet_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
