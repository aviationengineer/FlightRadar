# Fleet Intelligence Dashboard — Streamlit

Interactive dashboard over the Fleet Intelligence Google Sheet (snapshot 5 Nov 2026):
OpenSky registered fleets, Airline Fleet Monitor active fleets, AirLabs partial
snapshot, Skylink live airborne snapshot.

## Run locally

```bash
cd fleet-dashboard/STREAMLIT_DASHBOARD
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

## Analytics (Google Analytics 4)

The app reports anonymous usage to Google Analytics 4 (GA4) once a
Measurement ID is configured — until then tracking is completely off and
the app behaves exactly as before.

**What is tracked:** a `page_view` when the app loads. Tab switches
inside this single-page dashboard are client-side, so they are not sent
as separate events. No personal data is sent — no user IDs, no custom
dimensions, nothing that identifies a visitor. GA4 anonymises IP
addresses by default. The injection lives in `analytics.py`
(`inject_analytics`, called once in `app.py`).

**Setup (one GA4 property, three streams):** create one GA4 property
for the three Streamlit apps at https://analytics.google.com, then add
one web data stream per app URL
(`fleet-intelligence-2026.streamlit.app`,
`global-fleet-intelligence.streamlit.app`,
`aviationenterprisect.streamlit.app`). Each stream has its own
Measurement ID (`G-XXXXXXXXXX`). In Streamlit Cloud, open the app →
Manage app → Settings → Secrets and add:

```
GA_MEASUREMENT_ID = "G-XXXXXXXXXX"
```

(using this app's own stream ID). Tracking starts on the next run;
remove the secret to switch it off again. The ID can also be set as the
`GA_MEASUREMENT_ID` constant in `analytics.py`, but secrets are
preferred — never commit a real Measurement ID to the repo.

Note: Streamlit Cloud's built-in "App analytics" (view counts in the
Cloud dashboard) is separate from Google Analytics; this integration
does not affect it.
