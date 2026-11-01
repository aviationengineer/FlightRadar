"""Example: ingest OpenSky states into Google Sheets.

Usage:
    cp .env.example .env
    pip install -r requirements.txt
    python -m OPENSKY_FRAMEWORK_API.example_run --lamin 51 --lomin -1 --lamax 52 --lomax 1

Bounding box is optional – omit for worldwide (rate limits apply).
"""

from __future__ import annotations

import argparse, os, sys
sys.path.insert(0, os.path.expanduser("~/workspace"))
from dotenv import load_dotenv

from OPENSKY_FRAMEWORK_API.pipeline import OpenSkyIngestionPipeline


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description="Ingest OpenSky states to Google Sheets")
    p.add_argument("--lamin", type=float, default=None)
    p.add_argument("--lomin", type=float, default=None)
    p.add_argument("--lamax", type=float, default=None)
    p.add_argument("--lomax", type=float, default=None)
    args = p.parse_args()

    pipe = OpenSkyIngestionPipeline()
    print("Fetching OpenSky states...")
    res = pipe.run_states(lamin=args.lamin, lomin=args.lomin, lamax=args.lamax, lomax=args.lomax)
    if res.errors:
        print("Errors:", res.errors); sys.exit(1)
    print(f"Time: {res.time}, fetched {res.fetched}, wrote {res.written}, sheet {res.spreadsheet_id}")


if __name__ == "__main__":
    main()
