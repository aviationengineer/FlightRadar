"""Example: ingest AirLabs fleet data into Google Sheets.

Usage:
    cp .env.example .env   # add AIRLABS_API_KEY (free key from airlabs.co)
    pip install -r requirements.txt
    python -m AIRLABS_FLEET_API.example_run --mode full
    python -m AIRLABS_FLEET_API.example_run --mode weekly
    python -m AIRLABS_FLEET_API.example_run --mode airline --airline AA
    python -m AIRLABS_FLEET_API.example_run --mode full --dry-run   # no sheet writes

Modes:
    full    monthly paginated pull of the whole fleet DB (~600 requests
            estimated on a free key — measured on the first live run)
    weekly  refresh the rotating slice of top airlines, merged into the sheet
    airline refresh one airline by IATA code
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))

from dotenv import load_dotenv  # noqa: E402

from AIRLABS_FLEET_API.pipeline import AirlabsFleetPipeline  # noqa: E402


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ingest AirLabs fleet data to Google Sheets")
    parser.add_argument("--mode", choices=["full", "weekly", "airline"],
                        default="weekly", help="Run mode")
    parser.add_argument("--airline", default=None,
                        help="IATA code for --mode airline (e.g. AA)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch + transform, but do not write to Sheets")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Safety cap on API pages (dev/testing only)")
    args = parser.parse_args()

    if args.mode == "airline" and not args.airline:
        parser.error("--mode airline requires --airline (e.g. --airline AA)")

    pipeline = AirlabsFleetPipeline()
    if args.max_pages is not None:
        # Dev safety cap: monkey-patch the client's page walk.
        orig = pipeline.client._paged

        def capped(path, params, max_pages=None):  # noqa: ANN001, ANN202
            return orig(path, params, max_pages=args.max_pages)

        pipeline.client._paged = capped

    print(f"Running AirLabs {args.mode} ingestion"
          f"{' (dry run, no sheet writes)' if args.dry_run else ''} ...")
    if args.mode == "full":
        result = pipeline.run_full_refresh(write=not args.dry_run)
    elif args.mode == "weekly":
        result = pipeline.run_weekly_refresh(write=not args.dry_run)
    else:
        result = pipeline.run_airline_refresh(args.airline, write=not args.dry_run)

    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Status:   {result.status}")
    print(f"Fetched:  {result.fetched}")
    print(f"Deduped:  {result.deduped}")
    print(f"Written:  {result.written}")
    print(f"Requests: {result.requests_made} (cache_hit={result.cache_hit})")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Sheet ID: {result.spreadsheet_id}")
    print("Done.")


if __name__ == "__main__":
    main()
