"""Scheduled runner: ingest AirLabs fleet data into the Fleet Intelligence sheet.

Used by cron. Reads config from the environment.
Set AIRLABS_API_KEY (free key from https://airlabs.co) and optionally
AIRLABS_RUN_MODE (full | weekly, default weekly).

IMPORTANT: if the key is missing, this script logs a clear message and
exits 0 (graceful skip) so a cron job never errors loudly. No key is
ever created or requested on the user's behalf.

Example cron (monthly full pull, 1st of month 02:00 America/Edmonton):
    0 2 1 * * AIRLABS_RUN_MODE=full /usr/bin/python3 ~/workspace/AIRLABS_FLEET_API/schedule_run.py
Example cron (weekly refresh, Sundays 03:00):
    0 3 * * 0 AIRLABS_RUN_MODE=weekly /usr/bin/python3 ~/workspace/AIRLABS_FLEET_API/schedule_run.py
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from LIB.logging_utils import get_logger  # noqa: E402
from AIRLABS_FLEET_API.config import MISSING_KEY_MESSAGE  # noqa: E402
from AIRLABS_FLEET_API.pipeline import AirlabsFleetPipeline  # noqa: E402

log = get_logger("airlabs-schedule")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scheduled AirLabs fleet ingestion")
    parser.add_argument("--mode", choices=["full", "weekly"], default=None,
                        help="Run mode (overrides AIRLABS_RUN_MODE env)")
    args = parser.parse_args(argv)
    mode = args.mode or os.getenv("AIRLABS_RUN_MODE", "weekly").strip().lower()
    if mode not in ("full", "weekly"):
        log.error("Invalid mode %r (expected full|weekly)", mode)
        return 1

    if not os.getenv("AIRLABS_API_KEY"):
        # Graceful skip: no key yet, never an error, never a signup.
        log.warning("Skipping scheduled AirLabs run: %s", MISSING_KEY_MESSAGE)
        return 0

    pipeline = AirlabsFleetPipeline()
    if mode == "full":
        result = pipeline.run_full_refresh()
    else:
        result = pipeline.run_weekly_refresh()

    if result.status in ("error", "rate_limited"):
        log.error("Scheduled %s run failed (%s): %s",
                  mode, result.status, result.errors)
        return 1
    if result.status == "skipped_quota":
        log.warning("Scheduled %s run skipped: %s", mode, result.errors)
        return 0
    log.info("Scheduled %s run OK: fetched=%d written=%d requests=%d "
             "cache_hit=%s sheet=%s",
             mode, result.fetched, result.written, result.requests_made,
             result.cache_hit, result.spreadsheet_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
