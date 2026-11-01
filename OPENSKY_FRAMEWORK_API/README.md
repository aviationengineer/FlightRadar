# OpenSky Framework API

Class-based Python framework for the [OpenSky Network API](https://opensky-network.org/data/api)
(full reference: https://openskynetwork.github.io/opensky-api/ v1.4.0) → Google Sheets ingestion.
Uses the shared `LIB` master library.

## Endpoints covered

- `GET /states/all` – live state vectors (time, icao24, bbox lamin/lomin/lamax/lomax, extended)
- `GET /states/own` – your sensors only, no credit cost, auth required
- `GET /flights/all?begin=&end=` – flights in interval (≤2 h)
- `GET /flights/aircraft?icao24=&begin=&end=` – per aircraft (≤2 days, nightly batch)
- `GET /flights/arrival?airport=&begin=&end=` / `GET /flights/departure` – airport movements
- `GET /tracks/all?icao24=&time=` – trajectory, waypoints `[time, lat, lon, baro_alt, track, on_ground]`

## Auth

OAuth2 client-credentials only. Create an API client on your OpenSky account page,
then set `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET`. Tokens last 30 minutes;
the client refreshes proactively.

## Rate limits

- Anonymous 400/day, authenticated standard 4,000/day (per endpoint bucket).
- `/states/all` cost by bbox area: ≤25 sq° = 1 credit, 25–100 = 2, 100–400 = 3, >400 or global = 4.
- Anonymous: latest states only, 10 s resolution. Authenticated: up to 1 h old, 5 s resolution.
- 429 responses carry `X-Rate-Limit-Retry-After-Seconds`.

## Quickstart

```bash
cp .env.example .env
pip install -r requirements.txt
python -m OPENSKY_FRAMEWORK_API.example_run --lamin 51 --lomin -1 --lamax 52 --lomax 1
```

## Classes

- `OpenSkyConfig.from_env()`
- `OpenSkyClient.get_states(...)`, `.get_states_own(...)`, `.get_flights_all/aircraft/arrival/departure(...)`, `.get_tracks(...)`
- `OpenSkyState.from_vector()` – parses the 18-field state array
- `OpenSkyIngestionPipeline.run_states()` – fetch → append to Sheets

Sheet columns: `icao24, callsign, origin_country, latitude, longitude,
baro_altitude_m, geo_altitude_m, velocity_ms, true_track_deg,
vertical_rate_ms, on_ground, squawk, time_position, last_contact, category`

Note: the REST API has no schedules/delays/routes – research and non-commercial use.
