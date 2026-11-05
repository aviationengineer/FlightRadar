# Architecture

## Overview

```
┌──────────────┐      ┌───────────────────────────────┐      ┌────────────────────┐
│  AirLabs API │      │  Fleet Pipeline               │      │  Google Sheets     │
│  v9          │─────▶│                               │─────▶│  "Fleet           │
│  /fleets     │      │  Client → Models → Transforms │      │   Intelligence"    │
│  /airlines   │      │  → Cache/Quota → Sink         │      │  4 tabs            │
└──────────────┘      └───────────────────────────────┘      └────────────────────┘
```

## Classes

### AirlabsConfig
Immutable dataclass holding `api_key`, `base_url`, `page_size` (max 50 on
free keys), `timeout_seconds`, cache TTLs, `monthly_soft_cap` (900),
`weekly_slice_size` (10), and `top_airlines` (50 IATA codes).
Created via `AirlabsConfig.from_env()` which reads `AIRLABS_API_KEY` and
raises a clear "key missing — get a free key at airlabs.co" error when
absent. No key is stored anywhere in the repo.

### AirlabsClient (LIB BaseHTTPClient subclass)
Thin wrapper around AirLabs v9. Reuses LIB's retry/timeout/error mapping
instead of duplicating HTTP logic. Handles:
- Auth as `api_key` query param on every call (server-side only)
- Envelope unwrapping (`response` / `data` / bare list)
- Error payloads: AirLabs reports limits inside a 200 body
  (`{"error": {"code": "minute_limit_exceeded", ...}}`) — mapped to
  `AirlabsRateLimitError` with `limit_kind` minute/hour/month
- Pagination (`limit`/`offset`) until a short page arrives
- `_fields` on every call to slim payloads
- `request_count` so the pipeline can record/quota every request

Key methods:
- `get_fleets_page(limit, offset, **filters)` – one page, raw dicts
- `get_all_fleets(max_pages)` – full paginated pull → `list[FleetAircraft]`
- `get_airline_fleets(iata, icao)` – one airline's fleet
- `get_airline_names(max_pages)` – `{IATA|ICAO: name}` via `/airlines`

Minute limits are retried once after 65 s; hour/month limits fail fast.
HTTP 429s are already retried 3× by the LIB client, so the AirLabs layer
does not retry them again.

### FleetAircraft
Normalised dataclass. `from_api_dict()` is defensive: upper-cases hex /
registrations / airline codes, strips whitespace, coerces `age` to int,
maps the API's `icao` field to `icao_type`. `to_sheet_row()` returns
columns in sheet order; `key` (hex, else reg) is the dedupe/merge key.

### Transforms (pure functions)
- `normalize_aircraft` – stamp `fetched_at`, drop keyless records
- `dedupe_by_hex` – first occurrence wins
- `merge_fleets(existing, fresh)` – upsert by key, order-preserving
- `enrich_airline_names` – fill `airline_name` from the /airlines map
- `compute_quality_metrics` – totals, distinct counts, missing-field
  counts, duplicates removed, age outliers, avg age, % with age
- `rows_to_aircraft` / `aircraft_to_rows` – sheet round-trip for merges

### DiskCache / QuotaTracker (pipeline.py)
- `DiskCache` – JSON files under `data/cache/` with TTLs: full pull 28 d,
  per-airline 7 d, airline names 30 d. A cache hit costs zero requests.
- `QuotaTracker` – month-to-date request count in `data/state/quota.json`;
  resets automatically when the month rolls over. The pipeline refuses
  to start a full pull when `used + 600 (estimate) > 900 (soft cap)`.

### AirlabsSheetsSink
Wraps the shared LIB `GoogleSheetsSink` and adds what it lacks:
worksheet creation (`addSheet`), real per-tab `sheetId` lookup (LIB
hard-codes sheetId 0 for formatting), `format_tab` (bold header + light
fill + frozen row 1 + basic filter), `clear_tab`, `write_table` (full
replace, chunked ~100 KB with 0.5 s throttle) and chunked `append_rows`.
CLI contract: `--params <JSON>` for query params, `--json <JSON>` for
request bodies.

### AirlabsFleetPipeline
Orchestrates the flow:
1. Quota check (full mode only; weekly slices are small)
2. Cache-first fetch (full / per-airline / names)
3. `normalize_aircraft` → `enrich_airline_names` → `dedupe_by_hex`
4. Write: fleets (replace on full, merge on weekly/airline),
   quality (replace), log (append), catalog (replace)
5. Persist cache + quota state; return `IngestionResult`

Weekly slice: ISO-week rotation over the 50-airline list, 10 per week,
so each top-50 airline refreshes about every 5 weeks.

Returns `IngestionResult(run_type, status, fetched, deduped, written,
requests_made, cache_hit, duration_seconds, spreadsheet_id, errors)`.
Statuses: `ok`, `skipped_quota`, `rate_limited`, `error`.

## Data flow

1. Caller picks a mode: `full` (monthly), `weekly` (Sundays), or
   `airline:<IATA>`
2. Client GETs `/fleets?api_key=...&_fields=...&limit=50&offset=N`
   (plus `airline_iata=` for scoped pulls) until a short page
3. Raw dicts → `FleetAircraft.from_api_dict()` → `list[FleetAircraft]`
4. Transforms: normalize → enrich names → dedupe (full) or merge
   (weekly/airline, against rows read back from the sheet)
5. `FleetAircraft.sheet_headers()` + `to_sheet_row()` → 2D array
6. Sink writes chunked with `valueInputOption=USER_ENTERED`, then
   formats the header (bold/freeze/filter)

## Sheet schema

| Tab | Columns |
|-----|---------|
| AIRLABS_Fleets | hex, reg_number, airline_icao, airline_iata, airline_name, icao_type, model, manufacturer, age, fetched_at |
| AIRLABS_Data_Quality | metric, value, checked_at_utc |
| AIRLABS_Ingestion_Log | run_timestamp_utc, run_type, status, aircraft_fetched, aircraft_written, requests_made, cache_hit, duration_seconds, error |
| Fleet_Catalog | source, endpoint, coverage, refresh_cadence, quota_budget, last_run, status |

## Quota budget

Free tier: 1,000 req/month. Projected: full pull ~600 (estimate — measure
on first live run) + weekly ~160/month + names ~25 once = ~785/month,
~215 headroom. Soft cap 900 enforced by `QuotaTracker`. See README for
the full table and the fallback if the first live run measures higher.

## Extending

- Add a new endpoint: add a method to `AirlabsClient` using `_get_page()`
  (it counts requests and maps AirLabs error payloads)
- Add a new sink: implement `write_table(tab, headers, rows, replace)` /
  `append_rows(tab, rows, headers)` / `read_table(tab)`
- Add a transform: pure function in `transforms.py`
- Change the weekly set: edit `TOP_AIRLINES_IATA` in `config.py` or set
  `AIRLABS_WEEKLY_SLICE`
