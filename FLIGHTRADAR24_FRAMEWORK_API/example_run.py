"""Example: ingest live flights into Google Sheets.

Usage:
    cp .env.example .env   # add FR24_API_TOKEN
    pip install -r requirements.txt
    python -m flightradar24_ingestion.example_run --bounds "51.6,51.3,-0.6,0.1" --limit 50

Bounds format is "N,S,W,E".
Examples:
    London Heathrow area : "51.6,51.4,-0.6,-0.3"
    Edmonton (YEG) area  : "53.7,53.3,-113.7,-113.3"
    New York JFK area    : "40.8,40.5,-73.9,-73.6"
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

# Allow running as script from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flightradar24_ingestion.pipeline import FlightIngestionPipeline


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ingest FR24 live flights to Google Sheets")
    parser.add_argument("--bounds", required=True, help='Bounding box "N,S,W,E"')
    parser.add_argument("--limit", type=int, default=50, help="Max flights to write")
    parser.add_argument("--full", action="store_true", help="Use full (not light) endpoint")
    args = parser.parse_args()

    pipeline = FlightIngestionPipeline()
    print(f"Fetching live flights for bounds {args.bounds} ...")
    result = pipeline.run_live(bounds=args.bounds, full=args.full, limit=args.limit)

    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Fetched:  {result.fetched}")
    print(f"Deduped:  {result.deduped}")
    print(f"Written:  {result.written}")
    print(f"Sheet ID: {result.spreadsheet_id}")
    print("Done.")


if __name__ == "__main__":
    main()
