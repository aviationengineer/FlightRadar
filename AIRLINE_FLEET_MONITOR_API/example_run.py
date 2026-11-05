"""Example: ingest the Airline Fleet Monitor fleet snapshot to Google Sheets.

No API key needed — the source is a public, keyless open-data endpoint.

Usage:
    pip install -r requirements.txt
    python example_run.py                      # full export -> sheet
    python example_run.py --dry-run            # fetch + transform, no sheet write
    python example_run.py --airline delta-air-lines   # single-airline API check
    python example_run.py --sample             # offline run from data/sample_airlines.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/workspace"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from AIRLINE_FLEET_MONITOR_API.pipeline import FleetMonitorPipeline  # noqa: E402
from AIRLINE_FLEET_MONITOR_API.transforms import export_to_fleets, run_quality_checks  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest AFM fleet snapshot to Google Sheets")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + transform, do not write")
    parser.add_argument("--airline", default=None, help="Slug for a single-airline API check")
    parser.add_argument("--sample", action="store_true",
                        help="Offline run from data/sample_airlines.json")
    args = parser.parse_args()

    pipeline = FleetMonitorPipeline()

    if args.airline:
        fleet = pipeline.run_airline(args.airline)
        print(f"{fleet.airline} ({fleet.iata}/{fleet.icao}, {fleet.country})")
        print(f"  active={fleet.active} idle={fleet.idle_7_29d} "
              f"stored={fleet.stored_30d_plus} total={fleet.total} "
              f"avg_age={fleet.average_age}")
        return

    if args.sample:
        with open(os.path.join(os.path.dirname(__file__), "data", "sample_airlines.json")) as fh:
            raw = json.load(fh)
        fetched_at = datetime.now(timezone.utc).isoformat()
        fleets = export_to_fleets(raw, fetched_at=fetched_at)
        checks = run_quality_checks(raw, fleets, fetched_at=fetched_at)
        print(f"Sample: {len(raw)} raw records -> {len(fleets)} active fleets")
        for f in fleets:
            print(f"  {f.airline}: total={f.total} active={f.active}")
        for c in checks:
            print(f"  [{c.result}] {c.check}: {c.detail} = {c.value}")
        return

    print("Fetching AFM bulk export (https://airlinefleetmonitor.com/data/airlines.json) ...")
    result = pipeline.run_export(write=not args.dry_run)
    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"Fetched:          {result.fetched}")
    print(f"Airlines written: {result.airlines_written}")
    print(f"Total airframes:  {result.total_airframes}")
    print(f"Quality:          {result.quality}")
    print(f"Sheet ID:         {result.spreadsheet_id}")
    print("Done.")


if __name__ == "__main__":
    main()
