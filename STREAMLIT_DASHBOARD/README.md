# Fleet Intelligence Dashboard — Streamlit

Interactive dashboard over the Fleet Intelligence Google Sheet (snapshot 5 Nov 2026):
OpenSky registered fleets, Airline Fleet Monitor active fleets, AirLabs partial
snapshot, Skylink live airborne snapshot.

## Run locally

```bash
cd fleet-dashboard/streamlit
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Open http://localhost:8501 in your browser.

## Deploy (free) — Streamlit Community Cloud

1. Push this folder to a public GitHub repo (e.g. `aviationengineer/fleet-dashboard`).
2. Go to https://share.streamlit.io → New app → pick the repo, branch, and `app.py`.
3. Deploy. You get a public URL like `https://fleet-dashboard.streamlit.app`.

Streamlit Cloud redeploys automatically on every push to the repo.

## Refresh the data

The CSVs in `data/` are a snapshot of the Fleet Intelligence sheet as of
5 Nov 2026. To refresh: re-export the five tabs (OPENSKY_Counts, AFM_Fleets,
AIRLABS_Fleets, SKYLINK_Fleets, Fleet_Catalog) from the sheet into `data/`
and restart the app (or push the new CSVs — Streamlit Cloud picks them up).

## Pages

- **Overview** — KPI cards per source, top-10 fleets, airframes by country.
- **Airlines** — AFM joined to OpenSky on ICAO, searchable and filterable by country.
- **Fleet mix** — AirLabs manufacturer / model / age charts; Skylink airborne breakdowns.
- **Sources & quality** — source catalog and the per-source caveats.
