# OpenSky Framework API

Class-based Python framework for the [OpenSky Network API](https://opensky-network.org/data/api)
→ Google Sheets ingestion. Uses the shared `LIB` master library.

## Endpoints covered

- `GET /states/all` – live state vectors (anonymous or OAuth2)
- `GET /flights/all?begin=&end=` – flights in time window
- `GET /tracks/all?icao24=&time=` – track for an aircraft

## Quickstart

```bash
cp .env.example .env
pip install -r requirements.txt
python -m OPENSKY_FRAMEWORK_API.example_run --lamin 51 --lomin -1 --lamax 52 --lomax 1
```

Anonymous access is rate-limited; add `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET`
for higher limits (OAuth2 client credentials).

## Classes

- `OpenSkyConfig.from_env()`
- `OpenSkyClient.get_states(lamin, lomin, lamax, lomax)`
- `OpenSkyState.from_vector()` – parses the 18-field state array
- `OpenSkyIngestionPipeline.run_states()` – fetch → append to Sheets

Sheet columns: `icao24, callsign, origin_country, latitude, longitude,
baro_altitude_m, geo_altitude_m, velocity_ms, true_track_deg,
vertical_rate_ms, on_ground, squawk, time_position, last_contact, category`
