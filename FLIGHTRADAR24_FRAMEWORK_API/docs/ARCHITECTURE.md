# Architecture

## Overview

```
┌─────────────────┐      ┌──────────────────────┐      ┌───────────────────┐
│  FlightRadar24  │      │  Ingestion Framework │      │  Google Sheets    │
│  API            │─────▶│                      │─────▶│                   │
│  fr24api.       │      │  Client → Models →   │      │  Flights tab      │
│  flightradar24  │      │  Transforms → Sink   │      │  17 columns       │
│  .com           │      │                      │      │                   │
└─────────────────┘      └──────────────────────┘      └───────────────────┘
```

## Classes

### FR24Config
Immutable dataclass holding `api_token`, `base_url`, `api_version`, `timeout_seconds`.
Created via `FR24Config.from_env()` which reads `FR24_API_TOKEN`.

### FlightRadar24Client
Thin wrapper around REST API v1. Handles:
- Auth headers (`Authorization: Bearer`, `API-Version: v1`)
- Error mapping (401, 402, 429, 5xx → `FR24APIError`)
- Envelope unwrapping (`data` / `result` / `flights`)

Key methods:
- `get_live_positions_light(bounds)` – cheapest, for polling
- `get_live_positions_full(bounds)` – richer, more credits
- `get_airport_full(code)`, `get_airline_light(icao)`
- `get_flight_tracks(flight_id)`, `get_historic_positions_light()`

### Flight
Normalised dataclass. `from_api_dict()` is defensive against light/full shape
differences. `to_sheet_row()` returns columns in sheet order.

### GoogleSheetsSink
Writes via Hatch CLI (`/opt/hatch/bin/hatch_gws_cli`) so no service-account
JSON is needed when running inside Muse. Methods:
- `create_spreadsheet(title)` → returns spreadsheet ID
- `ensure_header()` – writes + freezes header if empty
- `append_flights(flights)` → returns rows written

For standalone use outside Muse, swap this for a `gspread` implementation
with the same interface (`append_flights`, `ensure_header`).

### FlightIngestionPipeline
Orchestrates the flow:
1. `ensure_sink()` – create sheet if needed
2. Fetch via client
3. `dedupe_by_fr24_id()`
4. Stamp `timestamp_utc` if missing
5. Append via sink

Returns `IngestionResult(fetched, deduped, written, spreadsheet_id, errors)`.

## Data flow

1. Caller provides bounds as `"N,S,W,E"` (e.g. `"51.6,51.4,-0.6,-0.3"`)
2. Client GETs `/api/live/flight-positions/light?bounds=...`
3. Raw dicts → `Flight.from_api_dict()` → `List[Flight]`
4. Optional transforms: `dedupe_by_fr24_id`, `filter_by_altitude`
5. `Flight.sheet_headers()` + `to_sheet_row()` → 2D array
6. Sink appends with `valueInputOption=USER_ENTERED`

## Sheet schema

| Column | Type | Source |
|--------|------|--------|
| timestamp_utc | string (ISO-8601) | API or pipeline now |
| fr24_id | string | API |
| callsign | string | API |
| flight_number | string | API |
| registration | string | API |
| aircraft_type | string | API |
| airline_icao | string | API |
| origin_iata/icao | string | API |
| destination_iata/icao | string | API |
| latitude/longitude | float | API |
| altitude_ft | int | API |
| ground_speed_kts | int | API |
| heading_deg | int | API |
| squawk | string | API |

## Extending

- Add a new endpoint: add a method to `FlightRadar24Client` using `_get()`
- Add a new sink: implement `append_flights(flights: list[Flight]) -> int`
- Add a transform: pure function in `transforms.py`
