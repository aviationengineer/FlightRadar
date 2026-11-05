"""Example: run a Skylink weekly ADS-B snapshot into Google Sheets.

Usage:
    cp .env.example .env   # add SKYLINK_RAPIDAPI_KEY
    pip install -r requirements.txt
    python example_run.py --airlines "Air Canada,WestJet" --limit-per-airline 50

Without --airlines, the default target list from config.py is used
(override with the SKYLINK_AIRLINES env var).
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from SKYLINK_API.config import MISSING_KEY_MESSAGE  # noqa: E402
from SKYLINK_API.pipeline import SkylinkIngestionPipeline  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Skylink weekly ADS-B snapshot → Google Sheets"
    )
    parser.add_argument(
        "--airlines",
        default=None,
        help='Comma-separated airline names, e.g. "Air Canada,WestJet"',
    )
    parser.add_argument(
        "--limit-per-airline", type=int, default=None,
        help="Cap aircraft written per airline",
    )
    parser.add_argument(
        "--sheet-id", default=None,
        help="Spreadsheet ID (default: Fleet Intelligence sheet)",
    )
    args = parser.parse_args()

    if not os.getenv("SKYLINK_RAPIDAPI_KEY"):
        print(MISSING_KEY_MESSAGE)
        sys.exit(1)

    pipeline = SkylinkIngestionPipeline()
    if args.sheet_id:
        pipeline.sink.spreadsheet_id = args.sheet_id
    airlines = (
        [a.strip() for a in args.airlines.split(",") if a.strip()]
        if args.airlines else None
    )
    print("Fetching weekly ADS-B snapshot ...")
    result = pipeline.run_weekly_snapshot(
        airlines=airlines, limit_per_airline=args.limit_per_airline
    )

    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Fetched:             {result.fetched}")
    print(f"Deduped:             {result.deduped}")
    print(f"Written:             {result.written}")
    print(f"ADS-B requests:      {result.adsb_requests}")
    print(f"Registration lookups:{result.registration_lookups}")
    print(f"Operators resolved:  {result.operators_resolved}")
    print(f"Sheet ID:            {result.spreadsheet_id}")
    for s in result.airline_summary:
        print(f"  {s['airline_name']}: {s['aircraft_observed']} airborne "
              f"[{s['aircraft_types']}]")
    print("Done.")


if __name__ == "__main__":
    main()
