# FlightRadar24 Ingestion Framework

Class-based Python framework to acquire live flight data from the official
FlightRadar24 API and pipe it into Google Sheets.

API docs: https://fr24api.flightradar24.com/docs  
Announcement: https://www.flightradar24.com/blog/b2b/flightradar24-api/

## What you get

- `FR24Config` – loads `FR24_API_TOKEN` from the environment
- `FlightRadar24Client` – thin wrapper around the REST API v1
  - `get_live_positions_light(bounds)` / `get_live_positions_full(bounds)`
  - `get_airport_full(code)`, `get_airline_light(icao)`
  - `get_flight_tracks(flight_id)`, historic positions, usage
- `Flight` – normalised dataclass with `from_api_dict()` and `to_sheet_row()`
- `GoogleSheetsSink` – writes via the Hatch Google Workspace CLI (no service-account JSON needed)
- `FlightIngestionPipeline` – orchestrates fetch → dedupe → append

Auth header used: `Authorization: Bearer <token>` + `API-Version: v1`  
Base URL: `https://fr24api.flightradar24.com`

## Quick start

1. Get a token: log in at https://fr24api.flightradar24.com → **Key management** → Create token.
   For free testing, use the **Sandbox** environment – it returns static data without spending credits.

2. Configure:

```bash
cp .env.example .env
# edit .env and set FR24_API_TOKEN
pip install -r requirements.txt
```

3. Run an ingestion (bounds are "N,S,W,E"):

```bash
python -m flightradar24_ingestion.example_run --bounds "51.6,51.4,-0.6,-0.3" --limit 50
```

This creates a Google Sheet (if `GOOGLE_SHEET_ID` is not set), writes the header row,
freezes it, and appends the flights.

### Bounds examples

| Area | Bounds (N,S,W,E) |
|------|------------------|
| London Heathrow | `51.6,51.4,-0.6,-0.3` |
| Edmonton YEG | `53.7,53.3,-113.7,-113.3` |
| New York JFK | `40.8,40.5,-73.9,-73.6` |

## Using the classes directly

```python
from dotenv import load_dotenv
load_dotenv()

from flightradar24_ingestion import FR24Config, FlightRadar24Client, FlightIngestionPipeline

# Low level: just fetch
config = FR24Config.from_env()
client = FlightRadar24Client(config)
flights = client.get_live_positions_light(bounds="51.6,51.4,-0.6,-0.3", limit=20)
for f in flights:
    print(f.callsign, f.origin_iata, "->", f.destination_iata, f.altitude_ft)

# High level: fetch + write to Sheets
pipeline = FlightIngestionPipeline()
result = pipeline.run_live(bounds="51.6,51.4,-0.6,-0.3", limit=50)
print(result)  # IngestionResult(fetched=..., written=..., spreadsheet_id=...)
```

### Multiple airports

```python
results = pipeline.run_for_airports({
    "Heathrow": "51.6,51.4,-0.6,-0.3",
    "JFK": "40.8,40.5,-73.9,-73.6",
}, limit_per_airport=30)
```

## Sheet layout

Columns written (in order):

`timestamp_utc, fr24_id, callsign, flight_number, registration, aircraft_type, airline_icao, origin_iata, origin_icao, destination_iata, destination_icao, latitude, longitude, altitude_ft, ground_speed_kts, heading_deg, squawk`

## Notes

- Start with the `light` endpoints – they cost fewer credits than `full`.
- The sandbox returns static responses with the same schema; ideal for development.
- Credits, rate limits and plan differences are described in the FR24 portal under Subscription & credits.
- `GoogleSheetsSink` uses `/opt/hatch/bin/hatch_gws_cli` so it works with the Sheets connection already authorised in Muse. For standalone use outside Muse, swap it for a `gspread` implementation.

## Project layout

```
flightradar24_ingestion/
├── __init__.py
├── config.py          # FR24Config.from_env()
├── fr24_client.py     # FlightRadar24Client
├── models.py          # Flight dataclass
├── transforms.py      # flights_to_rows, dedupe, filters
├── sheets_sink.py     # GoogleSheetsSink (via hatch_gws_cli)
├── pipeline.py        # FlightIngestionPipeline
├── example_run.py     # CLI example
└── README.md
```
