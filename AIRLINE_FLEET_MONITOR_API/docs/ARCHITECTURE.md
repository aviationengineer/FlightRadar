# Architecture

## Overview

```
┌──────────────────────┐      ┌──────────────────────┐      ┌───────────────────┐
│ Airline Fleet        │      │  Ingestion Framework │      │  Google Sheets    │
│ Monitor (public,     │─────▶│                      │─────▶│  "Fleet Intel."   │
│ keyless JSON)        │      │  Client → Models →   │      │  AFM_Fleets (860) │
│ /data/airlines.json  │      │  Transforms → Sink   │      │  AFM_Data_Quality │
│ /api/v1/*            │      │                      │      │  AFM_Ingestion_Log│
└──────────────────────┘      └──────────────────────┘      └───────────────────┘
```

## Live verification (2026-11-05, before any client code was written)

All checks were done with plain unauthenticated `curl` / `browser.open`.
No account was created, no key requested, nothing signed up for.

### What the site is

- Homepage: `https://www.airlinefleetmonitor.com/` (www 301s to apex).
  Static Astro site. Claims 28,450 active airframes / 482 airlines /
  3,512 airports as of 2026-09-17; homepage table lists the top 10
  airlines (Delta 1,388 … SkyWest 398) with Active / Idle (7–29d) /
  Stored (30d+) / Average Age / Coverage columns.
- Classification (site FAQ): Active = observed in flight telemetry
  within the last 7 days; Idle = unobserved 8–30 days; Stored =
  inactive 30+ days or at a storage airpark. (The homepage table header
  says "7–29d" for idle; the pipeline uses the column names
  `idle_7_29d` / `stored_30d_plus` per the task spec and notes the
  7/8-day wording difference here.)
- `robots.txt`: `Allow: /`, `Disallow: /api/internal/` only; sitemaps
  for core/aircraft/airlines/tools/compare/history/airports/airframes.

### API & Developer Portal — `/api-docs/`

- Base endpoint: **`/api/v1/`** on Cloudflare Workers / KV, "Edge
  Response Latency < 35 ms", "low-latency read-only JSON endpoints".
- OpenAPI 3.0 contract: **`GET /openapi.json`** → 200, 5,687 bytes.
  `info.title` "Airline Fleet Monitor Read-Only REST API", version
  1.0.0, licence **ODbL**,
  `servers: [{url: https://airlinefleetmonitor.com/api/v1}]`,
  **no `security` field, no `securitySchemes`** — no auth of any kind.
- Paths in `openapi.json`:
  - `GET /airlines/{slug}` — airline profile + fleet counts
  - `GET /aircraft/{slug}` — type specs + observed fleet counts
  - `GET /airframes/{tail}` — airframe by registration tail / Mode S hex
  - `GET /airports/{icao}` — airport profile + observed influx
  - `GET /lessors/{slug}` — lessor managed portfolio
- Documented on `/api-docs/` but **not** in `openapi.json`:
  `GET /api/v1/deliveries` — verified 200 live, `{"success": true,
  "data": {"total": 40, "deliveries": [...]}}`.
- Example from the docs page (verified shape live):
  `GET /api/v1/aircraft/a359` →
  `{"status": "success", "data": {"slug": "a359", "name": "Airbus A350-900",
  "icao_type": "A359", "manufacturer": "Airbus", "seats_typical": 315,
  "range_km": 15000, "mtow_kg": 280000, "observed_fleet_count": 578,
  "active_count": 552, "stored_count": 18}}`
- `GET /api/v1/airlines/delta-air-lines` → 200, 1,473 bytes,
  `{"success": true, "data": {id, wikidata_qid, name, iata, icao,
  callsign, country, founded, ceased, status, hubs, slug,
  observed_fleet_count, active_count, idle_count, stored_count,
  avg_age: null, coverage_confidence, observed_airframes_count,
  observed_airframes_sample: [...]}}`.
  Note: the per-airline endpoint returns **`avg_age: null`** where the
  bulk export carries a value — the export is the richer source.

### Data Export Hub — `/data-export/`

Bulk files, no auth, "updated continuously with every data pipeline
export run", "Licensed for research, editorial, and commercial
analytics use":

| File | Verified | Contents |
|------|----------|----------|
| `/data/airlines.json` | 200, 1,102,047 B | 2,500 airlines (860 active + 1,640 defunct) — **primary source** |
| `/data/aircraft_types.json` | 200, 83,918 B | Aircraft models & specs |
| `/data/airframes.json` | linked | Live Mode S / ADS-B airframe registry |
| `/data/routes.json` | linked | Trunk routes + weekly frequencies |
| `/data/lessors.json` | linked | Lessor portfolios |
| `/data/special_liveries.json` | linked | Special liveries |
| `/data/daily_social_briefing.json` | linked | Daily social cards |
| `/data/airlines_and_defunct_combined.csv` | linked | Combined directory (CSV) |
| `/data/airports.csv`, `/data/airworthiness_directives.csv` | linked | Airports / AD watchlist (CSV) |

One export record (real, Delta):
```json
{"id": 2, "wikidata_qid": "Q188920", "name": "Delta Air Lines",
 "iata": "DL", "icao": "DAL", "callsign": "DELTA",
 "country": "United States", "founded": "1925", "ceased": null,
 "status": "active",
 "hubs": ["KATL","KJFK","KLAX","KDTW","KMSP","KSLC","KBOS","KSEA"],
 "slug": "delta-air-lines", "observed_fleet_count": 1388,
 "active_count": 1388, "idle_count": 0, "stored_count": 0,
 "coverage_confidence": "high", "avg_age": 11.2}
```

### What the live data actually contains (measured 2026-11-05)

| Fact | Value |
|------|-------|
| Export records | 2,500 (860 active, 1,640 defunct) |
| Active fleets written | 860 (549 with total > 0, 311 with total == 0) |
| Sum of `total` over active fleets | 25,226 airframes |
| Sum of `observed_fleet_count` over all records | 27,825 (defunct carriers still carry counts, e.g. defunct Federal Express: 483 — hence the `status == "active"` filter) |
| Records with `idle_count` > 0 | **0 of 2,500** |
| Records with `stored_count` > 0 | **0 of 2,500** |
| Distinct `avg_age` values | **2** (0.0 and 11.2); 11.2 in 834 of 2,500 records, 549 of 860 active |
| Active fleets missing IATA | 197 of 860; missing ICAO: 0; missing country: 0 |
| `coverage_confidence` (active) | high=122, medium=258, low=480 |
| Site snapshot date | 2026-09-17 (export refresh cadence is the site's, not ours) |

Consequences, all surfaced in `AFM_Data_Quality` rather than hidden:
- The idle/stored **split carries no signal today** — columns are
  emitted (all 0) and flagged WARN. The homepage's aggregate 6.5%
  idle / 9.3% stored is not reproduced per airline anywhere in the
  public data.
- `average_age` is a site-wide placeholder (11.2 / 0.0), not a
  per-airline measurement. Do not chart it as if it varied by airline.
- The export is ~7 weeks stale at first ingestion; a weekly cadence is
  plenty — polling more often would only re-download the same file.

## Classes

### AFMConfig
Frozen dataclass, no secrets: `base_url`, `api_base_url`, `export_url`,
`timeout_seconds` (60 — the export is ~1.1 MB), `max_retries`,
`spreadsheet_id` (default: the Fleet Intelligence workbook),
`user_agent`. `from_env()` reads `AFM_*` / `GOOGLE_SHEET_ID`; nothing
is required — there is no token to set.

### AirlineFleetMonitorClient
Thin wrapper around the public endpoints. Uses `requests` with a
session built by `build_session()`: `trust_env=False`, explicit proxies
from the environment, `SSL_CERT_FILE` as CA bundle (this sandbox's
bracketed-IPv6 `no_proxy` breaks `trust_env` parsing in httpx/requests
— same lesson as the sibling frameworks). Retries network errors and
429s with backoff; maps 401/403/404/5xx to `AFMAPIError`. No auth
headers are sent — there is nothing to authenticate with.
- `get_airlines_export()` — bulk export (primary source, one request)
- `get_airlines_export_fleets(fetched_at)` — export parsed to models
- `get_airline(slug)`, `get_aircraft_type(slug)`,
  `get_airframe(tail_or_hex)`, `get_lessor(slug)`, `get_deliveries()`,
  `get_openapi()` — per-entity API (verification / spot checks)

### AirlineFleet
Normalised dataclass. `from_export_dict()` maps the export record
(`observed_fleet_count` → `total`, falling back to
active+idle+stored when null; `hubs` list → comma-joined string).
`from_api_dict()` unwraps the `{"success": true, "data": {...}}`
envelope and accepts `hubs` as a list or a JSON string.
`to_sheet_row()` matches `sheet_headers()` (13 columns).
Also: `DataQualityRow` (check/result/detail/value/fetched_at) and
`IngestionLogRow` (run_at/source/records/airlines/airframes/status/notes).

### Transforms (`transforms.py`)
- `export_to_fleets(raw, fetched_at)` — keep `status == "active"`,
  dedupe on ICAO (fallback slug, keep largest total), sort by total desc.
- `run_quality_checks(raw, fleets, fetched_at)` — 15 checks including
  split-sums-to-total, idle/stored populated (WARN when all zero),
  avg_age variance (WARN when ≤ 2 distinct values), IATA/ICAO/country
  coverage, zero-fleet carriers, confidence mix, total airframes.

### AFMSheetsSink (`sheets_sink.py`)
Built on shared `LIB/sheets.py` (`GoogleSheetsSink._run`) for the Hatch
CLI calls, with AFM-specific behaviour: resolves the real `sheetId`
per tab (LIB hardcodes 0), creates missing tabs via `addSheet`,
snapshot writes (clear + chunked `values.update`, ~90 KB/chunk,
0.5 s throttle — the CLI arg limit breaks on large single writes),
bold header + frozen row 1 + auto-filter, and an append-only
`append_rows()` for the ingestion log.

### FleetMonitorPipeline
1. Fetch bulk export (single request).
2. `export_to_fleets()` → active fleets.
3. `run_quality_checks()` → quality rows.
4. `write_snapshot(AFM_Fleets)`, `write_snapshot(AFM_Data_Quality)`,
   `append_rows(AFM_Ingestion_Log)`.
5. Returns `IngestionResult(fetched, airlines_written, total_airframes,
   quality, spreadsheet_id, errors)`; never throws — failures are
   reported in `result.errors` and logged as FAILED.

## Data flow

1. `GET https://airlinefleetmonitor.com/data/airlines.json` (no auth)
2. Raw list → `AirlineFleet.from_export_dict()` → `List[AirlineFleet]`
3. Filter active, dedupe, sort; quality checks
4. `AirlineFleet.sheet_headers()` + `to_sheet_row()` → 2D array
5. Sink replaces `AFM_Fleets` / `AFM_Data_Quality`, appends
   `AFM_Ingestion_Log` (USER_ENTERED)

## Sheet schema

### AFM_Fleets (13 columns, 860 rows + header)

| Column | Type | Source |
|--------|------|--------|
| airline | string | export `name` |
| iata | string | export `iata` (197 active carriers blank) |
| icao | string | export `icao` |
| country | string | export `country` |
| active | int | export `active_count` |
| idle_7_29d | int | export `idle_count` (0 for all records today) |
| stored_30d_plus | int | export `stored_count` (0 for all records today) |
| total | int | export `observed_fleet_count` (fallback: split sum) |
| average_age | float | export `avg_age` (placeholder: 0.0 or 11.2 only) |
| coverage_confidence | string | export `coverage_confidence` |
| slug | string | export `slug` |
| hubs | string | export `hubs`, comma-joined ICAO codes |
| fetched_at | string (ISO-8601 UTC) | pipeline run time |

### AFM_Data_Quality (5 columns, 15 rows + header)
check, result (PASS/WARN/FAIL), detail, value, fetched_at.

### AFM_Ingestion_Log (7 columns, append-only)
run_at, source, records_fetched, airlines_written, total_airframes,
status (OK/PARTIAL/FAILED), notes.

## Extending

- Add a new endpoint: add a method to `AirlineFleetMonitorClient`
  using `_get_json()` (see `get_deliveries()` for one that is documented
  on `/api-docs/` but absent from `openapi.json`).
- Add a new sink tab: add a `write_snapshot()` / `append_rows()` call
  in `pipeline.run_export()` with a model from `models.py`.
- Add a check: add a row in `transforms.run_quality_checks()`.
- If the site ever populates the idle/stored split or per-airline ages,
  no code change is needed — the columns and checks already exist; the
  WARNs will flip to PASS on their own.
