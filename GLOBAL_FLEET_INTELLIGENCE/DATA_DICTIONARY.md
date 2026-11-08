# Data Dictionary — Global Airline Fleet Intelligence

Snapshot date: **2026-11-05**. All tables live in `model/`, built by
`build_model.py` from the four Fleet Intelligence source CSVs. Source CSVs
are refreshed weekly from the live sheet by `../snapshot_weekly.py`, which
also appends one snapshot row per source to `FACT_FLEET_HISTORY_WEEKLY.csv`
and `WEEKLY_CHANGES.csv` (baseline 2026-11-08).

## DIM_AIRLINE (2,013 rows)

One row per airline. Key: `airline_id` = ICAO designator, or `operator_key`
(e.g. `IATA:SL`) for the 51 OpenSky operators with no ICAO code.

| Column | Meaning | Source / notes |
|---|---|---|
| airline_id | Join key (ICAO or operator_key) | AFM ∪ OpenSky |
| airline_name | Airline name | AFM preferred; OpenSky `operator_name` otherwise |
| iata_code | IATA code (2 chars) | AFM or OpenSky `operator_iata` |
| icao_code | ICAO designator (3 letters) | Blank for the 51 no-ICAO operators |
| country | Home country | AFM only; blank for OpenSky-only operators |
| region | 6-region aviation grouping | Mapped from country; "Unknown" if no country |
| airline_group | Parent group | **Blank — no source** |
| business_model | e.g. LCC / full-service / cargo | **Blank — no source** |
| afm_total_fleet | Total aircraft (AFM) | AFM snapshot 2026-09-17 |
| afm_active_fleet | Active aircraft (AFM) | Equals total; idle/stored are 0 in the source |
| opensky_registered_fleet | Registered aircraft (OpenSky) | Known-operator subset only |
| skylink_airborne | Airborne aircraft in the Skylink snapshot | Callsign-prefix match |
| airlabs_aircraft | Aircraft in the AirLabs snapshot | Mostly blank airline — see DQ |
| afm_avg_age | AFM average age | **Placeholder 11.2 in 549/860 rows — do not use as headline** |
| opensky_avg_built_year | Average built year | OpenSky; coverage in the next column |
| opensky_built_year_coverage_pct | % of fleet with a known built year | 31.2% overall |
| in_afm / in_opensky | Y/N source membership | |

## DIM_AIRCRAFT (523 rows)

One row per ICAO aircraft typecode present in any source.

| Column | Meaning |
|---|---|
| aircraft_id / aircraft_type | ICAO typecode (e.g. A320, B738, E190) |
| aircraft_family | A320 family, B737 family, B777, E-Jets, ATR, etc. |
| manufacturer | Airbus, Boeing, Embraer, ATR, Bombardier, Cessna, … or "Unknown" |
| body_type | Widebody / Narrowbody / Regional / Other |
| engine_family | **Blank — no source** |
| seat_capacity | **Blank — no source** |

## FACT_FLEET_SNAPSHOT (5,920 rows)

Grain: one row per (source, airline, aircraft type). `count` = aircraft in
that cell. `avg_age_years` is populated only where the source carries ages
(AirLabs); `age_coverage_pct` says how much of the cell it covers.

| Column | Meaning |
|---|---|
| snapshot_date | 2026-11-05 |
| source | afm / opensky / airlabs / skylink |
| airline_id / airline_name | Airline ("" for AirLabs — names blank in source) |
| aircraft_type / aircraft_family / manufacturer / body_type | Classified type |
| fleet_status | active (AFM) / registered (OpenSky) / in_service (AirLabs) / airborne (Skylink) |
| count | Aircraft in this cell |
| avg_age_years | Mean age where known |
| age_coverage_pct | % of the cell with a known age |

## FACT_AIRCRAFT_ORDER (0 rows) and FACT_FLEET_HISTORY (0 rows)

Schema only, by design. No order-book source is connected, and no full year
of history exists yet. The dashboard renders every dependent KPI as
`N/A — Data unavailable`.

## FACT_FLEET_HISTORY_WEEKLY (append-only) and WEEKLY_CHANGES (append-only)

Written by `../snapshot_weekly.py` each Monday, never by `build_model.py`.
One snapshot per week, starting 2026-11-08 (baseline). Week-over-week
change is real from the second snapshot on; growth YoY / CAGR need 12
months of snapshots. Net fleet change per airline is observable; gross
retirements vs deliveries are not (net deltas cannot split them).

| File | Columns | Grain |
|---|---|---|
| FACT_FLEET_HISTORY_WEEKLY.csv | snapshot_date, source, airline_id, fleet_count, active_fleet | one row per (week, source, airline) for AFM; one `ALL` row per source |
| WEEKLY_CHANGES.csv | snapshot_date, source, airline_id, metric, previous_value, current_value, delta, delta_pct | one row per non-zero week-over-week delta (source totals + top 10 AFM airline movers) |

## DATA_QUALITY (22 rows)

| Column | Meaning |
|---|---|
| source | afm / opensky / airlabs / skylink / all |
| check | What was tested |
| severity | HIGH / MEDIUM / LOW |
| affected_records / total_records | Scope of the issue |
| detail | Explanation and consequence |

## SOURCE_REGISTRY (6 rows)

| Column | Meaning |
|---|---|
| source_name | Source identifier |
| source_url | Where it came from (when known) |
| source_date | Date of the source data |
| retrieval_date | When it was pulled (2026-11-05) |
| data_confidence | HIGH / MEDIUM / LOW |
| record_count | Rows pulled |
| coverage | What the source covers |
| status | LIVE / partial |
