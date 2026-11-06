"""Fleet Intelligence Dashboard — Streamlit app.

Data: Fleet Intelligence Google Sheet, snapshot 2026-11-05.
CSVs in ./data are the snapshot; re-run fetch_data.py (or re-export the
sheet tabs) to refresh them. See README.md.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Fleet Intelligence Dashboard", layout="wide")

# Resolve the data dir from the script's own location: Streamlit Cloud runs
# the app from the repo root, so a bare relative "data" path breaks there.
DATA = Path(__file__).resolve().parent / "data"


@st.cache_data
def load(name):
    return pd.read_csv(DATA / f"{name}.csv")


afm = load("AFM_Fleets")
opensky = load("OPENSKY_Counts")
airlabs = load("AIRLABS_Fleets")
skylink = load("SKYLINK_Fleets")
catalog = load("Fleet_Catalog")

afm["total"] = pd.to_numeric(afm["total"], errors="coerce").fillna(0).astype(int)
afm["active"] = pd.to_numeric(afm["active"], errors="coerce").fillna(0).astype(int)
opensky["total_fleet"] = pd.to_numeric(
    opensky["total_fleet"], errors="coerce"
).fillna(0).astype(int)

st.title("Fleet Intelligence Dashboard")
st.caption("Source: Fleet Intelligence sheet  •  Snapshot: 5 Nov 2026  •  Four sources, four different measures — never sum them into one total.")

# ---------------- Overview ----------------
tab_overview, tab_airlines, tab_mix, tab_quality = st.tabs(
    ["Overview", "Airlines", "Fleet mix", "Sources & quality"]
)

with tab_overview:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("OpenSky registered", f"{opensky['total_fleet'].sum():,}",
              f"{len(opensky):,} operators")
    c2.metric("AFM active", f"{afm['total'].sum():,}", f"{len(afm):,} airlines")
    c3.metric("Skylink airborne now", f"{len(skylink):,}", "live ADS-B snapshot")
    c4.metric("AirLabs snapshot", f"{len(airlabs):,}", "PARTIAL — quota exhausted")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Largest registered fleets (OpenSky)")
        top_os = opensky.nlargest(10, "total_fleet")[["operator_name", "total_fleet"]]
        st.bar_chart(top_os.set_index("operator_name"))
    with col_b:
        st.subheader("Largest active fleets (AFM)")
        top_afm = afm.nlargest(10, "total")[["airline", "total"]]
        st.bar_chart(top_afm.set_index("airline"))

    st.subheader("Active airframes by country (AFM, top 10)")
    by_country = (
        afm.groupby("country")["total"].sum().sort_values(ascending=False).head(10)
    )
    st.bar_chart(by_country)

# ---------------- Airlines ----------------
with tab_airlines:
    st.subheader("Airlines — AFM active vs OpenSky registered")
    st.caption("Joined on ICAO code. 597 airlines appear in both sources.")
    joined = afm.merge(
        opensky[["operator_icao", "operator_name", "total_fleet"]],
        left_on="icao", right_on="operator_icao", how="left",
    )
    joined["total_fleet"] = joined["total_fleet"].fillna(0).astype(int)
    joined["variance"] = joined["total"] - joined["total_fleet"]
    view = joined[["airline", "iata", "icao", "country", "total",
                   "total_fleet", "variance"]].rename(columns={
        "total": "AFM active", "total_fleet": "OpenSky registered",
    }).sort_values("AFM active", ascending=False)

    q = st.text_input("Search airline, IATA or ICAO", "")
    countries = ["All"] + sorted(view["country"].dropna().unique().tolist())
    country = st.selectbox("Country", countries)
    filtered = view
    if q:
        m = (filtered["airline"].str.contains(q, case=False, na=False)
             | filtered["iata"].str.contains(q, case=False, na=False)
             | filtered["icao"].str.contains(q, case=False, na=False))
        filtered = filtered[m]
    if country != "All":
        filtered = filtered[filtered["country"] == country]
    st.dataframe(filtered, width='stretch', hide_index=True)
    st.caption(f"{len(filtered):,} airlines shown.")

# ---------------- Fleet mix ----------------
with tab_mix:
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("AirLabs — top manufacturers")
        st.bar_chart(airlabs["manufacturer"].value_counts().head(10))
        st.subheader("AirLabs — top models")
        st.bar_chart(airlabs["model"].value_counts().head(10))
        st.subheader("AirLabs — age buckets")
        ages = pd.to_numeric(airlabs["age"], errors="coerce").dropna()
        buckets = pd.cut(ages, [-1, 5, 15, 30, 200],
                         labels=["0–5", "6–15", "16–30", "31+"]).value_counts()
        st.bar_chart(buckets)
    with col_b:
        st.subheader("Skylink — airborne by airline (callsign prefix)")
        sk = skylink.copy()
        sk["prefix"] = sk["callsign"].fillna("").str[:3].replace("", "UNKNOWN")
        st.bar_chart(sk["prefix"].value_counts().head(10))
        st.subheader("Skylink — top aircraft types")
        st.bar_chart(skylink["aircraft_type"].value_counts().head(10))
        st.subheader("Skylink — top manufacturers")
        st.bar_chart(skylink["manufacturer"].value_counts().head(8))

# ---------------- Sources & quality ----------------
with tab_quality:
    st.subheader("Sources")
    st.dataframe(catalog, width='stretch', hide_index=True)
    st.subheader("Caveats — read before quoting any number")
    st.markdown("""
- **OpenSky** — registered airframes **with a known operator only**: 41,752 of
  520,000 in the raw database (8.0% have an operator code). Includes stored
  aircraft. Fleet-age coverage is only 31.2% overall.
- **Airline Fleet Monitor** — active fleets, 860 airlines / 25,226 airframes.
  Idle/stored columns are 0 for every record; average age 11.2 is a site-wide
  placeholder in 549 of 860 rows; site snapshot dated 2026-09-17.
- **AirLabs** — **partial snapshot only** (649 aircraft). The November quota was
  already exhausted before the 5 Nov pull. Airline names are blank on all rows.
- **Skylink** — live airborne snapshot, 762 unique aircraft across 10 target
  airlines (direct trial, 5 Nov – 5 Dec 2026). Airline names blank on all rows;
  operator resolution capped at 25 lookups per run.
""")
