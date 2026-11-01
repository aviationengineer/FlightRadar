# FlightRadar – FR24 Ingestion Framework

Class-based Python framework to acquire live flight data from the official
FlightRadar24 API and ingest it into Google Sheets.

- API docs: https://fr24api.flightradar24.com/docs
- Announcement: https://www.flightradar24.com/blog/b2b/flightradar24-api/

## Features

- 🔌 `FlightRadar24Client` – typed wrapper for FR24 API v1 (live, historic, airports, airlines, tracks)
- ✈️ `Flight` – normalised dataclass, resilient to light/full response differences
- 📊 `GoogleSheetsSink` – appends to Google Sheets via Hatch CLI (no service-account JSON needed in Muse)
- 🔄 `FlightIngestionPipeline` – one-call `run_live(bounds)` for fetch → dedupe → load
- 🧪 Sandbox support – test without spending credits

## Quickstart

### 1. Get an API token

Log in at https://fr24api.flightradar24.com → **Key management** → Create token.
For free testing use the **Sandbox** – static responses, same schema, no credit spend.

### 2. Configure

```bash
cp flightradar24_ingestion/.env.example .env
# edit .env → set FR24_API_TOKEN
pip install -r flightradar24_ingestion/requirements.txt
```

### 3. Run

```bash
# Bounds format: "N,S,W,E"
python -m flightradar24_ingestion.example_run --bounds "51.6,51.4,-0.6,-0.3" --limit 50
```

Examples:

| Area | Bounds |
|------|--------|
| London Heathrow | `51.6,51.4,-0.6,-0.3` |
| Edmonton YEG | `53.7,53.3,-113.7,-113.3` |
| New York JFK | `40.8,40.5,-73.9,-73.6` |

The pipeline creates a Google Sheet if `GOOGLE_SHEET_ID` is not set, writes the
header row, freezes it, and appends flights.

## Code example

```python
from dotenv import load_dotenv
load_dotenv()

from flightradar24_ingestion import FR24Config, FlightRadar24Client, FlightIngestionPipeline

# Low-level fetch
client = FlightRadar24Client(FR24Config.from_env())
flights = client.get_live_positions_light(bounds="51.6,51.4,-0.6,-0.3", limit=20)
for f in flights:
    print(f.callsign, f.origin_iata, "->", f.destination_iata, f.altitude_ft)

# High-level pipeline
pipeline = FlightIngestionPipeline()
result = pipeline.run_live(bounds="51.6,51.4,-0.6,-0.3", limit=50)
print(f"Fetched {result.fetched}, wrote {result.written} to {result.spreadsheet_id}")
```

See [docs/ARCHITECTURE.md](flightradar24_ingestion/docs/ARCHITECTURE.md) for class details
and sheet schema.

## Project structure

```
.
├── README.md
├── flightradar24_ingestion/
│   ├── __init__.py
│   ├── config.py          # FR24Config.from_env()
│   ├── fr24_client.py     # FlightRadar24Client
│   ├── models.py          # Flight dataclass
│   ├── transforms.py      # dedupe, filters
│   ├── sheets_sink.py     # GoogleSheetsSink
│   ├── pipeline.py        # FlightIngestionPipeline
│   ├── example_run.py     # CLI
│   ├── requirements.txt
│   └── docs/
│       └── ARCHITECTURE.md
```

## Sheet columns

`timestamp_utc, fr24_id, callsign, flight_number, registration, aircraft_type, airline_icao, origin_iata, origin_icao, destination_iata, destination_icao, latitude, longitude, altitude_ft, ground_speed_kts, heading_deg, squawk`

## Notes

- Prefer `light` endpoints for polling – fewer credits than `full`.
- Auth: `Authorization: Bearer <token>`, `API-Version: v1`.
- Base URL: `https://fr24api.flightradar24.com`.

## Licence

See LICENCE / LICENSE file.
