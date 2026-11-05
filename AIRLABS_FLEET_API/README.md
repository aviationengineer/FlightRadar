# AirLabs Fleet API Pipeline

Class-based Python pipeline that pulls the global airline fleet database
from the [AirLabs API (v9)](https://airlabs.co/docs/fleets) and writes it
into the **Fleet Intelligence** Google Sheet.

API docs: https://airlabs.co/docs/fleets

## What you get

- `AirlabsConfig` – loads `AIRLABS_API_KEY` from the environment; holds
  page size, cache TTLs, quota cap, and the top-50 airline list
- `AirlabsClient` – thin wrapper around `GET /fleets` (paginated) and
  `GET /airlines` (name enrichment), built on the shared LIB HTTP client
- `FleetAircraft` – normalised dataclass with `from_api_dict()` and
  `to_sheet_row()`
- `AirlabsSheetsSink` – writes via the Hatch Google Workspace CLI
  (no service-account JSON needed); chunked ~100 KB writes, bold/frozen/
  filtered headers, real per-tab sheetIds
- `AirlabsFleetPipeline` – orchestrates fetch → cache → transform →
  merge → Sheets, with quota tracking and an ingestion log
- `DiskCache` + `QuotaTracker` – on-disk caching (mandatory on the free
  tier) and month-to-date request accounting

Auth: `api_key` query parameter, server-side only.
Base URL: `https://airlabs.co/api/v9`

## Status

**No API key exists yet.** The pipeline is built and fully tested with
mocked HTTP, and the sheet tabs are created — but no live data has been
pulled. The first live run needs a free key (see Quick start).

## Quick start

1. Get a free key: sign up at https://airlabs.co, copy the key from your
   account dashboard. (This tool never signs up for a key on your behalf.)

2. Configure:

```bash
cp .env.example .env
# edit .env and set AIRLABS_API_KEY
pip install -r requirements.txt
```

3. Run an ingestion:

```bash
python -m AIRLABS_FLEET_API.example_run --mode full     # monthly full pull
python -m AIRLABS_FLEET_API.example_run --mode weekly   # weekly top-airline refresh
python -m AIRLABS_FLEET_API.example_run --mode airline --airline AA
python -m AIRLABS_FLEET_API.example_run --mode full --dry-run  # no sheet writes
```

If the key is missing, the runners fail with a clear
"key missing — get a free key at airlabs.co and set AIRLABS_API_KEY"
message, and `schedule_run.py` skips gracefully (exit 0) so cron never
errors loudly.

## Sheet layout

Destination: **Fleet Intelligence**
(`1cTgndcs_1egjtc8ND5cZvjrQPjHLpZeRIllnQTLBKHo`)

| Tab | Contents |
|-----|----------|
| `AIRLABS_Fleets` | One row per aircraft: `hex, reg_number, airline_icao, airline_iata, airline_name, icao_type, model, manufacturer, age, fetched_at` |
| `AIRLABS_Data_Quality` | `metric, value, checked_at_utc` — totals, distinct counts, missing-field counts, duplicates removed, age outliers |
| `AIRLABS_Ingestion_Log` | `run_timestamp_utc, run_type, status, aircraft_fetched, aircraft_written, requests_made, cache_hit, duration_seconds, error` |
| `Fleet_Catalog` | One row per source: `source, endpoint, coverage, refresh_cadence, quota_budget, last_run, status` — **owned by this pipeline**; the other fleet pipelines do not touch it |

Headers are bold with a light fill, frozen, and filtered. The fleets tab
is fully replaced on a monthly full pull; weekly/airline refreshes merge
into the existing rows by hex (registration as fallback).

## Quota budget (free tier: 1,000 requests/month, 250/min, 2,500/hour)

Caching is mandatory — every pull is cached on disk first
(full pull 28 days, per-airline 7 days, airline names 30 days), so a
re-run inside the TTL costs zero requests. `_fields` is used on every
call so only the needed columns cross the wire.

| Item | Projected requests | Notes |
|------|-------------------|-------|
| Monthly full pull | ~600 | Global fleet ~25,000–30,000 airframes ÷ 50 rows/request (free-key page size). **Estimate — the first live run must measure and record the real number** (it lands in `AIRLABS_Ingestion_Log.requests_made` and `data/state/quota.json`). |
| Weekly refresh | ~40/week, ~160/month | Rotating slice of 10 of the top-50 airlines (ISO-week rotation, so each top-50 airline is refreshed about every 5 weeks). |
| Airline names (`/airlines`) | ~25 once, then ~0 | Paginated once, cached 30 days; best-effort — a failure just leaves `airline_name` blank. |
| **Total projected** | **~785/month** | **~215 requests (~21%) headroom under the 1,000 limit.** |
| Soft cap | 900 | The pipeline refuses to start a pull past this; monthly usage is tracked in `data/state/quota.json`. |

If the first live run measures the full pull above ~650 requests,
reduce `AIRLABS_WEEKLY_SLICE` (e.g. to 5) or stretch the full pull to
every 6 weeks — the guardrail is the 900 soft cap, not the schedule.

Rate limits: `minute_limit_exceeded` is retried once after 65 s;
`hour_limit_exceeded` / `month_limit_exceeded` fail fast and are
recorded in the ingestion log with `status=rate_limited`.

## Recommended cron schedule

Monthly full pull — 1st of the month, 02:00 America/Edmonton:

```
0 2 1 * * AIRLABS_RUN_MODE=full /usr/bin/python3 ~/workspace/AIRLABS_FLEET_API/schedule_run.py
```

Weekly top-airline refresh — Sundays, 03:00 America/Edmonton:

```
0 3 * * 0 AIRLABS_RUN_MODE=weekly /usr/bin/python3 ~/workspace/AIRLABS_FLEET_API/schedule_run.py
```

## Using the classes directly

```python
from dotenv import load_dotenv
load_dotenv()

from AIRLABS_FLEET_API import AirlabsConfig, AirlabsClient, AirlabsFleetPipeline

# Low level: just fetch (paginated, counted)
config = AirlabsConfig.from_env()
client = AirlabsClient(config)
fleet = client.get_all_fleets()
print(len(fleet), "aircraft in", client.request_count, "requests")
aa = client.get_airline_fleets(iata="AA")

# High level: fetch + write to Sheets
pipeline = AirlabsFleetPipeline()
result = pipeline.run_full_refresh()
print(result)  # IngestionResult(fetched=..., written=..., requests_made=..., ...)
```

## Tests

```bash
python -m pytest tests/ -q   # 26 tests, mocked HTTP, no live key needed
```

Coverage: client pagination + `_fields`/filter params, minute/hour/month
limit mapping, HTTP 429 mapping, missing-key error, model normalisation,
dedupe/merge/round-trip, quality metrics, pipeline quota guard, disk-cache
hit (second run = 0 requests), weekly merge, and the scheduled runner's
graceful missing-key exit (0).

## Environment lessons applied

- The Sheets connector CLI takes query/path params via `--params <JSON>`
  and request bodies via `--json <JSON>` (see `sheets_sink.py`).
- Large frames are written in ~100 KB byte-sized chunks with a 0.5 s
  throttle between chunks (CLI argv length limit).
- HTTP goes through the shared `LIB` client (`requests`-based), so the
  `httpx` proxy/`SSL_CERT_FILE` workaround from other frameworks is not
  needed here.

## Project layout

```
AIRLABS_FLEET_API/
├── __init__.py
├── config.py          # AirlabsConfig.from_env(), top-50 list, quota budget
├── airlabs_client.py  # AirlabsClient (LIB BaseHTTPClient subclass)
├── models.py          # FleetAircraft dataclass
├── transforms.py      # normalize, dedupe, merge, quality metrics
├── sheets_sink.py     # AirlabsSheetsSink (LIB sheets + worksheet mgmt)
├── pipeline.py        # AirlabsFleetPipeline, DiskCache, QuotaTracker
├── schedule_run.py    # cron entry point (graceful skip when key missing)
├── example_run.py     # CLI example
├── requirements.txt
├── .env.example
├── tests/             # pytest suite (mocked HTTP)
├── data/cache/        # on-disk API cache (git-ignored in practice)
├── data/state/        # quota.json (month-to-date requests)
├── README.md
└── docs/ARCHITECTURE.md
```

## Notes

- The `/fleets` endpoint returns no airline *name* — names are enriched
  from `/airlines` (`name,iata_code,icao_code`) and cached for 30 days.
- `age` comes from the API as-is; `built` year is available in the raw
  payload but not stored (age is the sheet column).
- Never put `AIRLABS_API_KEY` in code, docs, or the repo. The API
  response echoes the key in its `request` block — the client never logs
  raw payloads or request params.
