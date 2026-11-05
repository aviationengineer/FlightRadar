# Skylink API Ingestion Framework

Class-based Python framework to build an operator's **active fleet picture**
from the Skylink API (via RapidAPI) and pipe it into Google Sheets.

Skylink is hosted on RapidAPI: `skylink-api.p.rapidapi.com`.
Free Basic tier: **1,000 requests/month, no credit card required**.

## How fleet visibility works

Fleet visibility comes from **live ADS-B**: each airborne aircraft carries
its airline and aircraft type, and a registration lookup resolves the
operator. So this pipeline builds an operator's ACTIVE fleet picture from
what's actually flying — not from a registry of airframes that may be
stored, retired, or never flown. Aircraft whose operator is unresolved
from the ADS-B record get a sparing registration lookup
(`GET /v3/aircraft/registration/{reg}`, 615k+ aircraft); everything else
is resolved from the live record alone.

## What you get

- `SkylinkConfig` – loads `SKYLINK_RAPIDAPI_KEY` from the environment
- `SkylinkClient` – thin wrapper around the Skylink API (RapidAPI)
  - `get_adsb_aircraft(...)` – live ADS-B, paginated; filter by airline
    name, callsign, icao24, registration, bbox, altitude
  - `get_aircraft_by_registration(reg)` – manufacturer, model, operator
  - `search_airline(icao=...)` / `search_airline(iata=...)` – icao OR
    iata, never both
- `AircraftObservation` – normalised dataclass with `from_api_dict()`
  and `to_sheet_row()`
- `SkylinkSheetsSink` – writes via the Hatch Google Workspace CLI
  (reuses the shared `LIB` sink; no service-account JSON needed),
  with per-tab creation, bold/frozen/filtered headers, and chunked
  appends (~100 KB per CLI call)
- `SkylinkIngestionPipeline` – orchestrates fetch → normalise → dedupe
  → sparing enrichment → quality checks → Sheets

Auth headers used on every request:
`X-RapidAPI-Key: <key>` + `X-RapidAPI-Host: skylink-api.p.rapidapi.com`

## Quick start

1. Get a free key: sign up at https://rapidapi.com/, search "Skylink",
   subscribe to the **Basic (free)** plan — 1,000 requests/month, no
   credit card. Copy the key.

2. Configure:

```bash
cp .env.example .env
# edit .env and set SKYLINK_RAPIDAPI_KEY
pip install -r requirements.txt
```

3. Run a weekly snapshot (default: 10 target airlines):

```bash
python example_run.py
# or a subset:
python example_run.py --airlines "Air Canada,WestJet" --limit-per-airline 50
```

This creates the `SKYLINK_Fleets`, `SKYLINK_Data_Quality`, and
`SKYLINK_Ingestion_Log` tabs in the **Fleet Intelligence** sheet
(`1cTgndcs_1egjtc8ND5cZvjrQPjHLpZeRIllnQTLBKHo`), writes and freezes
the header rows, and appends the snapshot.

## Quota budget & recommended schedule

Free tier: **1,000 requests/month**. The weekly snapshot is budgeted to
**~200 requests/month**:

| Item | Per weekly run | Per month (×4.33) |
|------|---------------|-------------------|
| ADS-B snapshot, 10 airlines × ~2 pages | ~20 | ~87 |
| Registration lookups (unresolved operators only, capped at 25/run) | ≤25 | ≤108 |
| **Total** | **≤45** | **~195** |

That leaves ~800 requests/month of headroom for ad-hoc airline searches,
extra pages, or additional target airlines. If you add airlines, each
one costs roughly 2 ADS-B requests per run (~9/month).

**Recommended cron — weekly, Monday 07:00 America/Edmonton:**

```
0 7 * * 1 /usr/bin/python3 ~/workspace/SKYLINK_API/schedule_run.py
```

`schedule_run.py` skips gracefully (logs + exit 0) when no key is set,
so the cron never errors loudly before a key exists. Do not create the
cron until a key is configured.

## Using the classes directly

```python
from dotenv import load_dotenv
load_dotenv()

from SKYLINK_API import SkylinkConfig, SkylinkClient, SkylinkIngestionPipeline

# Low level: just fetch
config = SkylinkConfig.from_env()
client = SkylinkClient(config)
obs = client.get_adsb_aircraft(airline="Air Canada", limit=20)
for o in obs:
    print(o.callsign, o.registration, o.aircraft_type, o.operator)
print("requests used:", client.requests_made)

# Airline lookup (icao OR iata, never both)
airlines = client.search_airline(icao="ACA")

# High level: weekly snapshot → Sheets
pipeline = SkylinkIngestionPipeline()
result = pipeline.run_weekly_snapshot()
print(result)  # IngestionResult(fetched=..., written=..., adsb_requests=...)
```

## Sheet layout

Tabs written in the **Fleet Intelligence** sheet (this pipeline writes
ONLY its `SKYLINK_*` tabs — never `Fleet_Catalog` or any other source's
tabs):

**SKYLINK_Fleets** — one row per observed aircraft:

`icao24, registration, callsign, airline_name, airline_icao, aircraft_type, model, manufacturer, operator, observed_at`

**SKYLINK_Data_Quality** — one row per check per run:

`check_name, checked_field, total_rows, failed_rows, pass_rate_pct, status, observed_at`

Checks: `registration_present`, `icao24_present`, `airline_resolved`,
`aircraft_type_present`, `callsign_present`, `icao24_unique`.
Status: PASS (≥95%), WARN (≥80%), FAIL (<80%).

**SKYLINK_Ingestion_Log** — one row per run, with the per-airline
summary in `notes`:

`run_at, source, airlines_targeted, adsb_requests, registration_lookups, aircraft_fetched, aircraft_written, operators_resolved, status, notes`

## Notes

- Transport reuses the shared `LIB` (`LIB.http.BaseHTTPClient`,
  requests-based), so the httpx `trust_env` / bracketed-IPv6 `no_proxy`
  problem does not apply.
- The Sheets CLI takes request bodies via `--json`, not `--params`;
  large appends are chunked to ~100 KB per call.
- Start with the default 10 airlines; add more via `SKYLINK_AIRLINES`
  (comma-separated) — each extra airline costs ~2 ADS-B requests/run.
- Registration lookups are capped at 25/run (`SKYLINK_MAX_REG_LOOKUPS`)
  and only spent on aircraft whose operator is unresolved from ADS-B.

## Project layout

```
SKYLINK_API/
├── __init__.py
├── config.py          # SkylinkConfig.from_env() / from_env_or_none()
├── skylink_client.py  # SkylinkClient (RapidAPI headers, pagination)
├── models.py          # AircraftObservation, RegistrationDetail, Airline,
│                      #   DataQualityRow, IngestionLogRow
├── transforms.py      # normalise, dedupe, per-airline summary, quality
├── sheets_sink.py     # SkylinkSheetsSink (LIB sink + tabs + chunking)
├── pipeline.py        # SkylinkIngestionPipeline
├── schedule_run.py    # cron runner (graceful skip without key)
├── example_run.py     # CLI example
├── requirements.txt
├── .env.example
├── tests/             # pytest, mocked HTTP, no live key needed
├── README.md
└── docs/
    └── ARCHITECTURE.md
```
