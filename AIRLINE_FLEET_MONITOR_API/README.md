# Airline Fleet Monitor — Fleet Ingestion Framework

Weekly snapshot of per-airline commercial fleet counts from
[Airline Fleet Monitor](https://airlinefleetmonitor.com/), an open-data
aviation intelligence platform (480+ airlines, ~28,450 active airframes,
ADS-B-derived). No API key, no account, no signup — the API and Data Export
Hub are public, keyless, read-only JSON under the ODbL licence (verified
live 2026-11-05; see `docs/ARCHITECTURE.md`).

> **What this is:** an **ACTIVE-fleet picture derived from ADS-B
> observation**, not a registered-fleet roster. An airframe counts as
> *active* when observed in flight telemetry within the last 7 days,
> *idle* when unobserved 8–30 days, *stored* when unobserved 30+ days
> (or at a storage airpark).

## What it produces

One row per active airline in the **Fleet Intelligence** workbook
(`1cTgndcs_1egjtc8ND5cZvjrQPjHLpZeRIllnQTLBKHo`):

| Tab | Contents |
|-----|----------|
| `AFM_Fleets` | 860 active airlines: airline, iata, icao, country, active, idle_7_29d, stored_30d_plus, total, average_age, coverage_confidence, slug, hubs, fetched_at |
| `AFM_Data_Quality` | 15 checks per run (PASS/WARN/FAIL) |
| `AFM_Ingestion_Log` | Append-only run log (one row per run) |

It touches **only** those three tabs — never `Fleet_Catalog` or any other
source's tabs.

## Live verification (2026-11-05)

- `GET https://airlinefleetmonitor.com/data/airlines.json` → **200**,
  1.1 MB, 2,500 records (860 active + 1,640 defunct). **No auth.**
- `GET https://airlinefleetmonitor.com/api/v1/airlines/delta-air-lines`
  → **200**, `{"success": true, "data": {...}}`. **No auth.**
- `GET https://airlinefleetmonitor.com/openapi.json` → OpenAPI 3.0,
  5 paths, **no security schemes**, licence ODbL.
- Also verified 200: `/api/v1/deliveries`, `/data/aircraft_types.json`.
- `robots.txt` allows `/`, disallows only `/api/internal/`.

**Known source limitations (flagged in AFM_Data_Quality, not hidden):**
- `idle_count` / `stored_count` are **0 for all 2,500 records** in the
  export, even though the homepage quotes 6.5% short-term idle / 9.3%
  long-term storage in aggregate. The columns are still emitted; the
  split simply carries no signal until the source populates it.
- `avg_age` takes only **two distinct values** (0.0 and 11.2) across the
  whole file — 11.2 in 549 of 860 active fleets — and the per-airline API
  returns `avg_age: null`. Treat it as a site-wide placeholder, not a
  per-airline measurement.
- The site's own snapshot date is **2026-09-17** (~7 weeks stale at first
  ingestion); the export is refreshed "with every data pipeline export
  run", so cadence is the site's, not ours.
- 197 of 860 active carriers have no IATA code; ICAO coverage is 100%.
- 311 active carriers have total == 0 (small / unobserved operators).

## Layout

```
AIRLINE_FLEET_MONITOR_API/
├── config.py            # AFMConfig (no token needed) — from_env()
├── afm_client.py        # AirlineFleetMonitorClient (export + /api/v1)
├── models.py            # AirlineFleet, DataQualityRow, IngestionLogRow
├── transforms.py        # export -> fleets, dedupe, quality checks
├── pipeline.py          # FleetMonitorPipeline orchestration
├── sheets_sink.py       # AFMSheetsSink (LIB-based, tab-aware, chunked)
├── schedule_run.py      # cron entry point (weekly)
├── example_run.py       # manual / dry-run / sample / single-airline
├── requirements.txt
├── .env.example         # no secrets; documents the (keyless) config
├── data/sample_airlines.json   # real-shape offline fixture (5 records)
├── tests/               # pytest, mocked HTTP, no network
├── README.md
└── docs/ARCHITECTURE.md
```

Reuses the shared `LIB/` (`http` patterns, `sheets`, `logging_utils`,
`config`) instead of duplicating them, mirroring
`FLIGHTRADAR24_FRAMEWORK_API/`.

## Usage

```bash
pip install -r requirements.txt
python example_run.py                 # live export -> sheet
python example_run.py --dry-run       # fetch + transform, no write
python example_run.py --sample        # offline, from data/sample_airlines.json
python example_run.py --airline delta-air-lines   # single-airline API check
python -m pytest tests/ -q            # 25 tests, mocked HTTP
```

Scheduled (weekly — the source itself updates infrequently; do not poll
it daily):

```
0 7 * * 1 /usr/bin/python3 ~/workspace/AIRLINE_FLEET_MONITOR_API/schedule_run.py
```

## Design notes

- **Primary source is the bulk export** (`/data/airlines.json`): one
  request for the whole directory, instead of 860 per-airline API calls.
  The per-airline endpoint is used only for spot checks (`--airline`).
- **Snapshot semantics**: `AFM_Fleets` and `AFM_Data_Quality` are
  cleared and rewritten each run; `AFM_Ingestion_Log` appends, so run
  history is preserved.
- **Chunked writes**: ~90 KB per Sheets `values.update` call, 0.5 s
  throttle — the Hatch CLI arg limit breaks on large single writes.
- **HTTP**: `requests` with `trust_env=False`, explicit proxies from the
  environment and `SSL_CERT_FILE` as CA bundle (this sandbox's
  bracketed-IPv6 `no_proxy` breaks `trust_env` parsing).
- Defunct/merged carriers (1,640) are excluded from `AFM_Fleets` — some
  still carry observed fleet counts, so filtering on `status == "active"`
  (not on fleet > 0) is what keeps the picture honest.
```

## Extending

- New endpoint: add a method to `AirlineFleetMonitorClient` using
  `_get_json()` (see `get_deliveries()` for one not in `openapi.json`).
- New sink tab: add a `write_snapshot()` / `append_rows()` call in
  `pipeline.run_export()` with a model from `models.py`.
- New check: add a row in `transforms.run_quality_checks()`.
