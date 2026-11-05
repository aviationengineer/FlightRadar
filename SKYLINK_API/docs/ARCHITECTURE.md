# Architecture

## Overview

```
┌─────────────────┐      ┌──────────────────────┐      ┌───────────────────┐
│  Skylink API    │      │  Ingestion Framework │      │  Google Sheets    │
│  (RapidAPI)     │─────▶│                      │─────▶│  "Fleet Intel."   │
│  skylink-api.p  │      │  Client → Models →   │      │  SKYLINK_Fleets   │
│  .rapidapi.com  │      │  Transforms → Sink   │      │  SKYLINK_Data_    │
│                 │      │                      │      │    Quality        │
│                 │      │                      │      │  SKYLINK_Ingest.  │
│                 │      │                      │      │    Log            │
└─────────────────┘      └──────────────────────┘      └───────────────────┘
```

## Fleet visibility model

Fleet visibility comes from **live ADS-B**: each airborne aircraft
carries its airline and aircraft type, and a registration lookup resolves
the operator. The pipeline therefore builds an operator's ACTIVE fleet
picture from what's actually flying — not from a registry of airframes
that may be stored or retired. Two consequences drive the design:

1. A snapshot is a point-in-time sample of airborne aircraft. Weekly
   runs accumulate a picture of the active fleet; a single run is not a
   complete registry.
2. Registration lookups are a scarce resource (quota), so they are spent
   only on aircraft whose operator is unresolved from the ADS-B record,
   capped at 25 per run.

## Classes

### SkylinkConfig
Immutable dataclass holding `api_key`, `base_url`, `rapidapi_host`,
`timeout_seconds`, `max_pages_per_airline`, `page_size`,
`max_registration_lookups`, `target_airlines`.
Created via `SkylinkConfig.from_env()` (raises `ValueError` with the
"key missing — get a free RapidAPI key" message) or
`SkylinkConfig.from_env_or_none()` (returns `None` for graceful
scheduled skips). Default target airlines: Air Canada, WestJet,
Emirates, Qatar Airways, British Airways, Lufthansa, Air France, KLM,
Delta Air Lines, Turkish Airlines (override with `SKYLINK_AIRLINES`).

### SkylinkClient (extends LIB.http.BaseHTTPClient)
Thin wrapper around the Skylink API. Reuses the shared LIB HTTP client
(requests-based, retries with backoff, 429/401/403 mapping), so the
httpx `trust_env` / bracketed-IPv6 `no_proxy` problem does not apply.
Adds the RapidAPI headers (`X-RapidAPI-Key`, `X-RapidAPI-Host`) and
request counting (`requests_made`, `adsb_requests`,
`registration_lookups`).

Key methods:
- `get_adsb_aircraft(airline, callsign, icao24, registration, bbox,
  min/max_altitude, limit)` – `GET /v3/adsb/aircraft`, paginated
  (`page`/`per_page`, stops on a short page or
  `max_pages_per_airline`); envelope unwrapping handles
  `data` / `results` / `aircraft` / bare-list shapes.
- `get_aircraft_by_registration(reg)` – `GET
  /v3/aircraft/registration/{reg}` (615k+ aircraft).
- `search_airline(icao=...)` / `search_airline(iata=...)` – `GET
  /airlines/search`; raises `ValueError` if both or neither are given.

### AircraftObservation
Normalised dataclass. `from_api_dict()` is defensive against flat vs
nested (`airline: {name, icao}`, `aircraft: {type, model}`) shapes.
`to_sheet_row()` returns columns in sheet order. `operator_resolved`
is True when airline/operator/ICAO is known from the ADS-B record.
Also: `RegistrationDetail`, `Airline`, `DataQualityRow`,
`IngestionLogRow` (each with `sheet_headers()` / `to_sheet_row()`).

### Transforms (pure functions)
- `normalize_registration` / `normalize_callsign` / `normalize_observations`
  – uppercase/dash-strip registrations, stamp missing `observed_at`,
  backfill `operator` from `airline_name`.
- `dedupe_by_icao24` – one row per airframe per snapshot.
- `summarize_by_airline` – aircraft observed + type breakdown per airline.
- `run_quality_checks` – completeness/uniqueness checks with
  PASS (≥95%) / WARN (≥80%) / FAIL thresholds.

### SkylinkSheetsSink (extends LIB.sheets.GoogleSheetsSink)
Reuses the LIB sink's Hatch CLI transport (`/opt/hatch/bin/hatch_gws_cli`,
`--json` bodies, `--params` for query/path values) and adds:
- `ensure_tab(tab_name)` – creates the tab if missing, returns its sheetId.
- `ensure_header_for_tab(tab_name, headers)` – writes the header if the
  tab is empty, then bolds it, freezes row 1, and sets a basic filter —
  against the tab's real sheetId (the LIB default of sheetId 0 is only
  correct for the first tab).
- `chunk_rows(rows, max_json_bytes=100_000)` + `append_rows_to_tab(...)` –
  appends in ~100 KB JSON chunks so the CLI arg limit is never hit.

### SkylinkIngestionPipeline
Orchestrates the weekly snapshot:
1. One ADS-B query per target airline (paginated, capped).
2. Normalise + dedupe by icao24.
3. `enrich_unresolved()` – registration lookups only for unresolved
   operators, capped per run; failures are logged, never fatal.
4. Per-airline summary + quality checks.
5. Append to `SKYLINK_Fleets`, `SKYLINK_Data_Quality`,
   `SKYLINK_Ingestion_Log` (summary in the log row's `notes`).
   A failed run still writes a `FAILED` log row when possible.

Returns `IngestionResult(fetched, deduped, written, adsb_requests,
registration_lookups, operators_resolved, quality_rows,
airline_summary, spreadsheet_id, errors)`.

### schedule_run.py / example_run.py
- `schedule_run.py` – cron entry point. No key → log the
  "get a free RapidAPI key" message and exit 0 (graceful skip).
  Recommended cron: weekly, Monday 07:00 America/Edmonton.
- `example_run.py` – CLI: `--airlines`, `--limit-per-airline`, `--sheet-id`.

## Quota budget

Free Basic tier: 1,000 requests/month. Weekly snapshot, 10 airlines:

| Item | Per run | Per month (×4.33) |
|------|---------|-------------------|
| ADS-B (10 airlines × ~2 pages) | ~20 | ~87 |
| Registration lookups (capped 25) | ≤25 | ≤108 |
| **Total** | **≤45** | **~195** |

~800 requests/month headroom remains for ad-hoc searches and extra
airlines (~9 requests/month per added airline).

## Sheet schema

| Tab | Columns |
|-----|---------|
| SKYLINK_Fleets | icao24, registration, callsign, airline_name, airline_icao, aircraft_type, model, manufacturer, operator, observed_at |
| SKYLINK_Data_Quality | check_name, checked_field, total_rows, failed_rows, pass_rate_pct, status, observed_at |
| SKYLINK_Ingestion_Log | run_at, source, airlines_targeted, adsb_requests, registration_lookups, aircraft_fetched, aircraft_written, operators_resolved, status, notes |

The pipeline writes ONLY its `SKYLINK_*` tabs in the shared
"Fleet Intelligence" workbook. It never touches `Fleet_Catalog` or any
other source's tabs.

## Extending

- Add a new endpoint: add a method to `SkylinkClient` using
  `_get_counted()` (keeps the request counter accurate).
- Add a new sink tab: call `sink.append_rows_to_tab(tab, headers, rows)`.
- Add a transform: pure function in `transforms.py`.
- Add a target airline: append to `SKYLINK_AIRLINES` (env) — budget
  ~2 ADS-B requests per run per airline.
