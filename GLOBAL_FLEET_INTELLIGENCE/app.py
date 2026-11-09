"""GLOBAL AIRLINE FLEET INTELLIGENCE — executive fleet dashboard.

Pages: 1 Executive Overview · 2 Fleet Composition · 3 Fleet Age & Replacement
       4 Future Fleet & Order Book · 5 Competitive Benchmark
       6 Data Quality & Sources

Data: the analytical model in ./model (built by build_model.py from the four
Fleet Intelligence sources, snapshot 2026-11-05, refreshed weekly by
snapshot_weekly.py). Every KPI without a source
renders as an explicit N/A placeholder — nothing is fabricated.
"""
import altair as alt
import pandas as pd
import streamlit as st

from analytics import inject_analytics
import kpis
from kpis import (UNAVAILABLE_KPIS, body_type_split, flag_age,
                  fleet_by_region, generate_insights, load_model,
                  load_weekly_history, manufacturer_split, top_airlines,
                  weekly_change_summary)

st.set_page_config(page_title="Global Airline Fleet Intelligence",
                   page_icon="✈️", layout="wide")

# ------------------------------------------------------------- theme / CSS
st.markdown("""
<style>
  .kpi { background:#131E33; border:1px solid #1F2E4D; border-radius:10px;
         padding:14px 16px; margin-bottom:10px; }
  .kpi .lbl { color:#8FA3C0; font-size:12px; letter-spacing:.08em;
              text-transform:uppercase; }
  .kpi .val { color:#FFFFFF; font-size:28px; font-weight:700; line-height:1.15; }
  .kpi .sub { color:#B8C6DA; font-size:12px; }
  .kpi.na { border:1px solid #B7791F; background:#2A2113; }
  .kpi.na .val { color:#F6AD55; }
  .insight { background:#0E2A3F; border-left:4px solid #00B4D8;
             border-radius:6px; padding:12px 16px; color:#D6E4F0;
             font-size:14px; margin:8px 0 18px 0; }
  .napanel { background:#2A2113; border:1px solid #B7791F; border-radius:10px;
             padding:18px 20px; color:#FBD38D; }
  .def { color:#8FA3C0; font-size:12px; }
  h1, h2, h3 { color:#FFFFFF; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------- data
model = load_model()
dim, fact, s = model["dim"], model["fact"], model["summary"]
SNAPSHOT = s["snapshot_date"]


def kpi_card(label, value, sub="", na=False):
    cls = "kpi na" if na else "kpi"
    val = "N/A" if na else str(value)
    sub_html = (f'<div class="sub">{sub}</div>' if sub else "")
    st.markdown(f'<div class="{cls}"><div class="lbl">{label}</div>'
                f'<div class="val">{val}</div>{sub_html}</div>',
                unsafe_allow_html=True)


def na_panel(title, detail):
    st.markdown(f'<div class="napanel"><b>{title}</b><br>{detail}</div>',
                unsafe_allow_html=True)


def insight_bar(text):
    st.markdown(f'<div class="insight">✈ {text}</div>',
                unsafe_allow_html=True)


def bar_h(df, x, y, title, color="#00B4D8"):
    chart = (alt.Chart(df).mark_bar(color=color)
             .encode(x=alt.X(x, title=None),
                     y=alt.Y(y, sort="-x", title=None),
                     tooltip=list(df.columns))
             .properties(title=title, height=380))
    st.altair_chart(chart, use_container_width=True)


def bar_v(df, x, y, title, color="#00B4D8"):
    chart = (alt.Chart(df).mark_bar(color=color)
             .encode(x=alt.X(x, title=None),
                     y=alt.Y(y, title=None),
                     tooltip=list(df.columns))
             .properties(title=title, height=320))
    st.altair_chart(chart, use_container_width=True)


# ------------------------------------------------------------- sidebar
st.sidebar.title("✈ Fleet Intelligence")
page = st.sidebar.radio(
    "Pages",
    ["1 · Executive Overview", "2 · Fleet Composition",
     "3 · Fleet Age & Replacement", "4 · Future Fleet & Order Book",
     "5 · Competitive Benchmark", "6 · Data Quality & Sources"])
# Google Analytics (GA4): page_view on load, page_navigation event when
# the sidebar page changes. Does nothing until GA_MEASUREMENT_ID is set
# in Streamlit secrets.
inject_analytics(page_name=page)
st.sidebar.markdown("---")
st.sidebar.subheader("Global filters")
regions = sorted(dim["region"].dropna().unique())
sel_region = st.sidebar.multiselect("Region", regions, default=regions)
countries = sorted(dim.loc[dim["region"].isin(sel_region), "country"]
                        .dropna().unique())
sel_country = st.sidebar.multiselect("Country", countries, default=[])
mfrs = sorted(fact["manufacturer"].unique())
sel_mfr = st.sidebar.multiselect("Manufacturer", mfrs, default=[])
bodies = sorted(fact["body_type"].unique())
sel_body = st.sidebar.multiselect("Body type", bodies, default=[])
airline_q = st.sidebar.text_input("Airline search (name or ICAO)", "")
st.sidebar.markdown("---")
st.sidebar.subheader("Age-flag thresholds")
t_green = st.sidebar.slider("GREEN: avg age up to (yrs)", 5.0, 15.0, 10.0, 0.5)
t_amber = st.sidebar.slider("AMBER: avg age up to (yrs)", 10.0, 20.0, 15.0, 0.5)
thresholds = {"green_max_age": t_green, "amber_max_age": t_amber,
              "green_max_over15_pct": 20.0, "amber_max_over15_pct": 35.0}
st.sidebar.markdown("---")
st.sidebar.markdown(f"**Data as of:** {SNAPSHOT}")
st.sidebar.markdown("**Source coverage:** 4 sources · "
                    "AFM 860 airlines · OpenSky 1,750 operators · "
                    "AirLabs 649 aircraft (partial) · Skylink 762 airborne")
st.sidebar.markdown("**Data confidence:** MEDIUM — see Data Quality page")

# apply filters
d = dim[dim["region"].isin(sel_region)].copy()
if sel_country:
    d = d[d["country"].isin(sel_country)]
if airline_q:
    q = airline_q.strip().upper()
    d = d[d["airline_name"].str.upper().str.contains(q, na=False)
          | d["icao_code"].str.upper().str.contains(q, na=False)]
f = fact[fact["airline_id"].isin(set(d["airline_id"]))].copy()
if sel_mfr:
    f = f[f["manufacturer"].isin(sel_mfr)]
if sel_body:
    f = f[f["body_type"].isin(sel_body)]
insights = generate_insights(model)

# ------------------------------------------------- country centroids (approx)
CENTROIDS = {
    "United States": (39.8, -98.6), "China": (35.9, 104.2),
    "India": (21.1, 78.9), "United Kingdom": (54.5, -2.0),
    "Germany": (51.2, 10.4), "France": (46.6, 2.4),
    "Japan": (36.2, 138.3), "United Arab Emirates": (24.0, 54.0),
    "Qatar": (25.3, 51.2), "Turkey": (38.9, 35.2),
    "Canada": (56.1, -106.3), "Australia": (-25.3, 133.8),
    "Brazil": (-14.2, -51.9), "Ireland": (53.2, -8.2),
    "Netherlands": (52.2, 5.3), "Spain": (40.2, -3.7),
    "Italy": (41.9, 12.5), "Russia": (61.5, 90.0),
    "Russian Federation": (61.5, 90.0), "Saudi Arabia": (25.0, 45.0),
    "Republic of Korea": (36.4, 127.9), "South Korea": (36.4, 127.9),
    "Singapore": (1.35, 103.8), "Thailand": (15.9, 101.0),
    "Malaysia": (4.2, 102.0), "Indonesia": (-2.5, 118.0),
    "Mexico": (23.6, -102.5), "Argentina": (-35.4, -65.2),
    "Chile": (-33.5, -70.7), "Colombia": (4.6, -74.1),
    "Peru": (-9.2, -75.0), "Egypt": (26.8, 30.8),
    "South Africa": (-30.6, 22.9), "Nigeria": (9.1, 8.7),
    "Kenya": (0.5, 37.9), "Morocco": (31.8, -6.1),
    "Ethiopia": (9.1, 40.5), "Poland": (52.0, 19.4),
    "Austria": (47.6, 14.1), "Belgium": (50.5, 4.5),
    "Switzerland": (46.8, 8.2), "Sweden": (62.0, 15.0),
    "Norway": (64.5, 11.5), "Denmark": (56.0, 10.0),
    "Finland": (64.0, 26.0), "Portugal": (39.6, -8.0),
    "Greece": (39.1, 22.0), "Philippines": (13.4, 122.0),
    "Vietnam": (14.1, 108.3), "Pakistan": (30.4, 69.3),
    "Bangladesh": (24.0, 90.4), "New Zealand": (-41.8, 172.8),
    "Hong Kong SAR of China": (22.3, 114.2), "Taiwan": (23.7, 121.0),
    "Israel": (31.0, 34.8), "Jordan": (31.2, 36.5),
    "Kuwait": (29.3, 47.5), "Oman": (21.5, 55.9),
    "Kazakhstan": (48.0, 66.9), "Ukraine": (49.0, 32.0),
}

# ============================================================ PAGE 1
def page_overview():
    st.title("GLOBAL AIRLINE FLEET INTELLIGENCE")
    st.caption("Executive Fleet Overview · snapshot " + SNAPSHOT +
               " · AFM active fleets · OpenSky registered fleets · "
               "AirLabs + Skylink per-aircraft snapshot")
    insight_bar(insights[0] + " " + insights[1])
    c = st.columns(4)
    with c[0]:
        kpi_card("Total Fleet (AFM)", f"{int(d['afm_total_fleet'].sum()):,}",
                 "Active airlines, AFM snapshot 2026-09-17")
    with c[1]:
        kpi_card("Active Fleet (AFM)", f"{int(d['afm_active_fleet'].sum()):,}",
                 "Idle/stored are 0 in the source — see Data Quality")
    with c[2]:
        kpi_card("Registered Fleet (OpenSky)",
                 f"{int(d['opensky_registered_fleet'].sum()):,}",
                 "Known-operator subset only (41,752 of ~520k)")
    with c[3]:
        kpi_card("Airlines in view", f"{len(d[d['afm_total_fleet'] > 0])}",
                 f"{len(d)} operators in the model (AFM + OpenSky)")
    body = body_type_split(f)
    tot_body = sum(body.values())
    c = st.columns(4)
    with c[0]:
        kpi_card("Average Fleet Age (AirLabs)",
                 f"{s['airlabs_avg_age']} yrs",
                 "337 of 649 aircraft have an age value")
    with c[1]:
        kpi_card("Widebody %",
                 f"{body.get('Widebody', 0) / tot_body * 100:.1f}%"
                 if tot_body else "N/A",
                 "Per-aircraft snapshot (AirLabs + Skylink)")
    with c[2]:
        kpi_card("Narrowbody %",
                 f"{body.get('Narrowbody', 0) / tot_body * 100:.1f}%"
                 if tot_body else "N/A",
                 "Per-aircraft snapshot (AirLabs + Skylink)")
    with c[3]:
        wh_dates = load_weekly_history()["dates"]
        hist_sub = ("Weekly history started " + wh_dates[0] +
                    "; YoY needs 12 months of snapshots") if wh_dates else \
            "No fleet-history source connected"
        kpi_card("Fleet Growth YoY %", "", hist_sub, na=True)
    c = st.columns(4)
    with c[0]:
        kpi_card("Aircraft on Order", "", "No order-book source connected",
                 na=True)
    with c[1]:
        kpi_card("Fleet Utilization", "",
                 "No block-hours / cycles source connected", na=True)
    with c[2]:
        kpi_card("Fleet CAGR", "", hist_sub, na=True)
    with c[3]:
        kpi_card("Replacement Ratio", "",
                 "Needs retirements + deliveries — no source", na=True)

    st.subheader("Airline Fleet Ranking")
    top = top_airlines(d, 20)
    bar_h(top.rename(columns={"afm_total_fleet": "Total fleet (AFM)"}),
          "Total fleet (AFM)", "airline_name", "Top 20 airlines by total fleet")
    st.markdown('<p class="def">Toggle: AFM total fleet. OpenSky registered '
                'fleet is the alternative view on the Composition page. '
                'Total fleet = all aircraft attributed to the airline; '
                'active fleet = in-service aircraft (AFM reports active = '
                'total because idle/stored are 0 in its feed).</p>',
                unsafe_allow_html=True)

    st.subheader("Fleet by Region")
    reg = fleet_by_region(d).reset_index()
    reg.columns = ["Region", "Active fleet (AFM)"]
    bar_v(reg, "Region", "Active fleet (AFM)", "Active fleet by region (AFM)")

    st.subheader("Global Fleet Map — fleet by home country (AFM)")
    by_country = (d[d["afm_total_fleet"] > 0]
                  .groupby("country")["afm_total_fleet"].sum()
                  .sort_values(ascending=False).head(30).reset_index())
    by_country["lat"] = by_country["country"].map(
        lambda x: CENTROIDS.get(x, (None, None))[0])
    by_country["lon"] = by_country["country"].map(
        lambda x: CENTROIDS.get(x, (None, None))[1])
    by_country = by_country.dropna(subset=["lat", "lon"])
    st.map(by_country, latitude="lat", longitude="lon",
           size="afm_total_fleet", color="#00B4D8")
    st.markdown('<p class="def">Bubble size = AFM active fleet in the '
                'country. Positions are approximate country centroids; '
                'countries without a centroid are omitted.</p>',
                unsafe_allow_html=True)

    st.subheader("Fleet Composition by Body Type")
    f_ps = f[f["source"].isin(["airlabs", "skylink"])].copy()
    f_ps = f_ps.merge(d[["airline_id", "region"]], on="airline_id",
                      how="left")
    comp = (f_ps.groupby(["region", "body_type"])["count"].sum()
            .reset_index())
    if not comp.empty:
        chart = (alt.Chart(comp).mark_bar()
                 .encode(x=alt.X("region", title=None),
                         y=alt.Y("count", title="Aircraft"),
                         color=alt.Color("body_type", title="Body type"),
                         tooltip=["region", "body_type", "count"])
                 .properties(title="Body-type mix by region "
                             "(per-aircraft snapshot)", height=320))
        st.altair_chart(chart, use_container_width=True)
    st.markdown('<p class="def">100% stacked view is the same data as '
                'shares — see the Composition page for percentages.</p>',
                unsafe_allow_html=True)

    st.subheader("Weekly Fleet Change")
    wcs = weekly_change_summary()
    if wcs is None:
        wh0 = load_weekly_history()
        if wh0["dates"]:
            na_panel("Baseline established " + wh0["dates"][0],
                     "First week-over-week comparison lands after the next "
                     "Monday snapshot. Growth YoY and CAGR need 12 months "
                     "of snapshots.")
        else:
            na_panel("N/A — Data unavailable",
                     "Fleet growth needs a fleet-history source "
                     "(year-over-year snapshots). FACT_FLEET_HISTORY is "
                     "empty by design until a history source is connected.")
    else:
        st.markdown(f"Week over week: {wcs['previous_date']} → "
                    f"{wcs['latest_date']} ({wcs['n_snapshots']} snapshots "
                    f"since {wcs['first_date']}).")
        chg = wcs["changes"]
        if chg is None or chg.empty:
            st.markdown("No change detected this week — all source totals "
                        "unchanged.")
        else:
            st.dataframe(chg, use_container_width=True, hide_index=True)
    st.subheader("Top Aircraft Order Books")
    na_panel("N/A — Data unavailable",
             "Order books need an order-book source (e.g. manufacturer "
             "order data, ch-aviation, or verified fleet tables). "
             "FACT_AIRCRAFT_ORDER is empty by design.")

# ============================================================ PAGE 2
def page_composition():
    st.title("FLEET COMPOSITION")
    st.caption("Manufacturer, family and body-type mix · snapshot " + SNAPSHOT)
    insight_bar(insights[3] + " " + insights[2])
    f_ps = f[f["source"].isin(["airlabs", "skylink"])].copy()
    tot = int(f_ps["count"].sum())
    mfr = manufacturer_split(f_ps)
    body = body_type_split(f_ps)
    c = st.columns(5)
    with c[0]:
        kpi_card("Total Aircraft", f"{tot:,}",
                 "Per-aircraft snapshot (AirLabs + Skylink)")
    with c[1]:
        kpi_card("Airbus Aircraft",
                 f"{int(f_ps[f_ps['manufacturer'] == 'Airbus']['count'].sum()):,}",
                 f"{mfr.get('Airbus', 0)}% of per-aircraft snapshot")
    with c[2]:
        kpi_card("Boeing Aircraft",
                 f"{int(f_ps[f_ps['manufacturer'] == 'Boeing']['count'].sum()):,}",
                 f"{mfr.get('Boeing', 0)}% of per-aircraft snapshot")
    with c[3]:
        kpi_card("Embraer Aircraft",
                 f"{int(f_ps[f_ps['manufacturer'] == 'Embraer']['count'].sum()):,}",
                 f"{mfr.get('Embraer', 0)}% of per-aircraft snapshot")
    with c[4]:
        kpi_card("ATR Aircraft",
                 f"{int(f_ps[f_ps['manufacturer'] == 'ATR']['count'].sum()):,}",
                 f"{mfr.get('ATR', 0)}% of per-aircraft snapshot")
    c = st.columns(4)
    with c[0]:
        kpi_card("Narrowbody %",
                 f"{body.get('Narrowbody', 0)}%",
                 "Per-aircraft snapshot")
    with c[1]:
        kpi_card("Widebody %", f"{body.get('Widebody', 0)}%",
                 "Per-aircraft snapshot")
    with c[2]:
        kpi_card("Regional %", f"{body.get('Regional', 0)}%",
                 "Per-aircraft snapshot")
    with c[3]:
        kpi_card("Other / GA %", f"{body.get('Other', 0)}%",
                 "Includes 233 AirLabs rows with no typecode")

    st.subheader("Manufacturer Split")
    mfr_df = (pd.DataFrame(
        [{"Manufacturer": k, "Aircraft": v}
         for k, v in sorted(mfr.items(), key=lambda x: -x[1])]))
    bar_v(mfr_df, "Manufacturer", "Aircraft",
          "Manufacturer split — per-aircraft snapshot (AirLabs + Skylink)")
    st.markdown('<p class="def">AirLabs raw manufacturer field is blank on '
                '36% of rows; the dashboard derives manufacturer from the '
                'ICAO typecode instead. 233 AirLabs rows have no typecode at '
                'all and stay "Unknown".</p>', unsafe_allow_html=True)

    st.subheader("Manufacturer Split — OpenSky top types (partial coverage)")
    osk = f[f["source"] == "opensky"].copy()
    osk_mfr = (osk.groupby("manufacturer")["count"].sum()
               .sort_values(ascending=False).reset_index())
    osk_mfr.columns = ["Manufacturer", "Aircraft (top-5 types only)"]
    bar_v(osk_mfr.head(10), "Manufacturer", "Aircraft (top-5 types only)",
          "OpenSky: manufacturer from each operator's top-5 types")

    st.subheader("Aircraft Family Ranking")
    fam = (f_ps.groupby("aircraft_family")["count"].sum()
           .sort_values(ascending=False).head(15).reset_index())
    fam.columns = ["Aircraft family", "Aircraft"]
    bar_h(fam, "Aircraft", "Aircraft family",
          "Top 15 aircraft families — per-aircraft snapshot")

    st.subheader("Body-Type Distribution")
    body_df = pd.DataFrame([{"Body type": k, "Aircraft": v}
                            for k, v in body.items()])
    bar_v(body_df, "Body type", "Aircraft",
          "Body-type distribution — per-aircraft snapshot")

    st.subheader("Airline × Aircraft Family Heatmap")
    sk = f[f["source"] == "skylink"].copy()
    sk = sk[sk["airline_id"] != "UNKNOWN"]
    top_al = (sk.groupby("airline_id")["count"].sum().nlargest(10).index)
    top_fam = (sk.groupby("aircraft_family")["count"].sum().nlargest(8).index)
    hm = sk[sk["airline_id"].isin(top_al)
            & sk["aircraft_family"].isin(top_fam)]
    hm = (hm.groupby(["airline_id", "aircraft_family"])["count"].sum()
          .reset_index())
    if not hm.empty:
        chart = (alt.Chart(hm).mark_rect()
                 .encode(x=alt.X("aircraft_family", title="Aircraft family"),
                         y=alt.Y("airline_id", title="Airline (ICAO)"),
                         color=alt.Color("count", title="Aircraft",
                                         scale=alt.Scale(scheme="blues")),
                         tooltip=["airline_id", "aircraft_family", "count"])
                 .properties(title="Airline × family (Skylink airborne "
                             "snapshot, 10 target airlines)", height=380))
        st.altair_chart(chart, use_container_width=True)
    st.markdown('<p class="def">AirLabs rows carry no airline name, so the '
                'heatmap uses the Skylink airborne snapshot only.</p>',
                unsafe_allow_html=True)

    st.subheader("Manufacturer Dependency — Airbus vs Boeing by Airline")
    dep = (sk.groupby(["airline_id", "manufacturer"])["count"].sum()
           .unstack(fill_value=0).reset_index())
    for col in ("Airbus", "Boeing"):
        if col not in dep.columns:
            dep[col] = 0
    dep["total"] = dep[["Airbus", "Boeing"]].sum(axis=1)
    dep = dep[dep["total"] > 0].copy()
    dep["Airbus %"] = (100 * dep["Airbus"] / dep["total"]).round(1)
    dep["Boeing %"] = (100 * dep["Boeing"] / dep["total"]).round(1)
    dep = dep.sort_values("total", ascending=False).head(10)
    dep_long = dep.melt(id_vars=["airline_id"],
                        value_vars=["Airbus %", "Boeing %"],
                        var_name="Manufacturer", value_name="Share %")
    chart = (alt.Chart(dep_long).mark_bar()
             .encode(x=alt.X("airline_id", title="Airline (ICAO)"),
                     y=alt.Y("Share %", title="Share of Airbus+Boeing (%)"),
                     color=alt.Color("Manufacturer"),
                     tooltip=["airline_id", "Manufacturer", "Share %"])
             .properties(title="Airbus vs Boeing dependency — Skylink "
                         "airborne snapshot", height=340))
    st.altair_chart(chart, use_container_width=True)
    st.markdown('<p class="def">Airbus Dependency = Airbus fleet / total '
                'fleet; Boeing Dependency = Boeing fleet / total fleet. '
                'Shown here on Airbus+Boeing aircraft only, Skylink '
                'snapshot.</p>', unsafe_allow_html=True)


# ============================================================ PAGE 3
def page_age():
    st.title("FLEET AGE & REPLACEMENT")
    st.caption("Fleet aging intelligence · snapshot " + SNAPSHOT)
    insight_bar(insights[4])
    bands = s["airlabs_age_bands"]
    aged_total = sum(bands.values())
    c = st.columns(4)
    with c[0]:
        kpi_card("Average Fleet Age (AirLabs)",
                 f"{s['airlabs_avg_age']} yrs",
                 f"{aged_total} of 649 aircraft have an age value")
    with c[1]:
        kpi_card("Aircraft <5 Years", f"{bands.get('<5', 0)}",
                 f"{100 * bands.get('<5', 0) / aged_total:.0f}% of aged aircraft")
    with c[2]:
        kpi_card("Aircraft 5–10 Years", f"{bands.get('5-10', 0)}",
                 f"{100 * bands.get('5-10', 0) / aged_total:.0f}% of aged aircraft")
    with c[3]:
        kpi_card("Aircraft 10–15 Years", f"{bands.get('10-15', 0)}",
                 f"{100 * bands.get('10-15', 0) / aged_total:.0f}% of aged aircraft")
    c = st.columns(4)
    with c[0]:
        kpi_card("Aircraft 15–20 Years", f"{bands.get('15-20', 0)}",
                 f"{100 * bands.get('15-20', 0) / aged_total:.0f}% of aged aircraft")
    with c[1]:
        kpi_card("Aircraft >20 Years", f"{bands.get('>20', 0)}",
                 f"{100 * bands.get('>20', 0) / aged_total:.0f}% of aged aircraft")
    with c[2]:
        kpi_card("Aircraft Retired", "",
                 "No fleet-history source connected", na=True)
    with c[3]:
        kpi_card("Replacement Ratio", "",
                 "Needs retirements + deliveries — no source", na=True)

    st.subheader("Fleet Age Distribution (AirLabs)")
    band_df = pd.DataFrame(
        [{"Age band": k, "Aircraft": v} for k, v in
         [("<5 years", bands.get("<5", 0)), ("5–10 years", bands.get("5-10", 0)),
          ("10–15 years", bands.get("10-15", 0)),
          ("15–20 years", bands.get("15-20", 0)),
          (">20 years", bands.get(">20", 0))]])
    bar_v(band_df, "Age band", "Aircraft",
          "Age distribution — AirLabs aircraft with a known age")

    st.subheader("Fleet Renewal Profile")
    renewal = pd.DataFrame([
        {"Profile": "New aircraft (<5 yrs)", "Aircraft": bands.get("<5", 0)},
        {"Profile": "Aging aircraft (>15 yrs)",
         "Aircraft": bands.get("15-20", 0) + bands.get(">20", 0)},
    ])
    bar_v(renewal, "Profile", "Aircraft",
          "New vs aging aircraft — AirLabs (age known on 337 of 649)")
    st.markdown('<p class="def">A full renewal profile needs deliveries and '
                'retirements by year — no history source is connected, so '
                'this is a snapshot comparison only.</p>',
                unsafe_allow_html=True)

    st.subheader("Average Fleet Age by Airline")
    age_df = kpis.avg_age_by_airline(d).head(20)
    if not age_df.empty:
        age_df = age_df.rename(columns={
            "airline_name": "Airline", "avg_age": "Avg age (yrs)",
            "coverage": "Built-year coverage %",
            "opensky_registered_fleet": "Registered fleet"})
        chart = (alt.Chart(age_df).mark_bar(color="#F6AD55")
                 .encode(x=alt.X("Avg age (yrs)", title="Avg age (yrs)"),
                         y=alt.Y("Airline", sort="-x", title=None),
                         tooltip=["Airline", "Avg age (yrs)",
                                  "Built-year coverage %",
                                  "Registered fleet"])
                 .properties(title="20 oldest fleets — OpenSky-derived age "
                             "(built-year coverage ≥ 50%)", height=420))
        st.altair_chart(chart, use_container_width=True)
    st.markdown('<p class="def">Age = 2026 − average built year. OpenSky '
                'built-year coverage is only 31.2% overall (US carriers '
                '80–95%, Chinese/European 0–1%), so only airlines with '
                '≥50% coverage are shown. AFM average age is NOT used: '
                '549 of 860 AFM rows share the placeholder 11.2.</p>',
                unsafe_allow_html=True)

    st.subheader("Age-Risk Flags")
    st.markdown('<p class="def">Thresholds (configurable in the sidebar): '
                f"GREEN avg age ≤ {thresholds['green_max_age']} yrs · "
                f"AMBER ≤ {thresholds['amber_max_age']} yrs · "
                "RED above. No thresholds were invented silently — these "
                "are the documented defaults.</p>", unsafe_allow_html=True)
    if not age_df.empty:
        flag_rows = []
        for _, r in age_df.iterrows():
            flag_rows.append({
                "Airline": r["Airline"], "Avg age (yrs)": r["Avg age (yrs)"],
                "Built-year coverage %": r["Built-year coverage %"],
                "Flag": flag_age(r["Avg age (yrs)"], t=thresholds),
            })
        flag_df = pd.DataFrame(flag_rows)
        st.dataframe(flag_df, use_container_width=True, hide_index=True)
        reds = flag_df[flag_df["Flag"] == "RED"]
        if not reds.empty:
            st.warning(f"{len(reds)} airline(s) flagged RED — high aging / "
                       "replacement pressure. Replacement orders are N/A, "
                       "so replacement pressure cannot be offset-checked.")

    st.subheader("Aircraft Retirement Trend")
    na_panel("N/A — Data unavailable",
             "Retirement trends need a fleet-history source (retirements by "
             "year). FACT_FLEET_HISTORY is empty by design.")

# ============================================================ PAGE 4
def page_future():
    st.title("FUTURE FLEET & ORDER BOOK")
    st.caption("Future fleet growth · snapshot " + SNAPSHOT)
    insight_bar(insights[5])
    c = st.columns(4)
    with c[0]:
        kpi_card("Aircraft on Order", "", "No order-book source connected",
                 na=True)
    with c[1]:
        kpi_card("Options", "", "No order-book source connected", na=True)
    with c[2]:
        kpi_card("Firm Orders", "", "No order-book source connected",
                 na=True)
    with c[3]:
        kpi_card("Deliveries Next 12 Months", "",
                 "No order-book source connected", na=True)
    c = st.columns(4)
    with c[0]:
        kpi_card("Deliveries Next 3 Years", "",
                 "No order-book source connected", na=True)
    with c[1]:
        kpi_card("Order-to-Fleet Ratio", "",
                 "Orders / current fleet — no order source", na=True)
    with c[2]:
        kpi_card("Expected Fleet Growth", "",
                 "Needs firm orders − expected retirements", na=True)
    with c[3]:
        kpi_card("Expected Future Fleet", "",
                 "Current fleet + firm orders − retirements", na=True)

    st.subheader("Current Fleet vs Aircraft on Order")
    na_panel("N/A — Data unavailable",
             "Order-to-Fleet Ratio = Aircraft on Order / Current Fleet. "
             "Expected Fleet Growth = (Current Fleet + Firm Orders − "
             "Expected Retirements − Current Fleet) / Current Fleet. Both "
             "need an order-book source; none is connected.")
    st.subheader("Order Book by Airline")
    na_panel("N/A — Data unavailable",
             "FACT_AIRCRAFT_ORDER is empty by design. Candidate sources: "
             "manufacturer order data, ch-aviation fleet database, or "
             "verified fleet tables (e.g. Wikipedia fleet lists, "
             "cross-checked against airline annual reports).")
    st.subheader("Order Book by Manufacturer")
    na_panel("N/A — Data unavailable",
             "Same order-book gap as above. Do not read manufacturer "
             "order share from the current-fleet split — it measures the "
             "installed fleet, not future commitments.")
    st.subheader("Aircraft Delivery Timeline")
    na_panel("N/A — Data unavailable",
             "Delivery timelines need order rows with delivery_year and "
             "delivery_month. The FACT_AIRCRAFT_ORDER schema already has "
             "these fields; it needs a source to fill them.")
    st.subheader("Expected Fleet Growth")
    na_panel("N/A — Data unavailable",
             "Forecasts are clearly separated from actuals in this product: "
             "everything on this page is a forecast input, and every one of "
             "them is currently unavailable. No estimate is shown as data.")


# ============================================================ PAGE 5
def page_benchmark():
    st.title("COMPETITIVE AIRLINE BENCHMARK")
    st.caption("Strategic positioning · snapshot " + SNAPSHOT)
    insight_bar(insights[0] + " " + insights[4])
    age_df = kpis.avg_age_by_airline(d)
    bench = d[d["afm_total_fleet"] > 0].merge(
        age_df[["airline_id", "avg_age", "coverage"]], on="airline_id",
        how="left")
    st.subheader("Fleet Scale vs Fleet Age")
    st.markdown('<p class="def">Quadrants are age-based: growth data is '
                'N/A, so the Y-axis uses average fleet age (OpenSky-derived) '
                'instead of fleet growth %. Bubble size = OpenSky registered '
                'fleet. Airlines without ≥50% built-year coverage are shown '
                'without an age value and are excluded from the scatter.</p>',
                unsafe_allow_html=True)
    scat = bench[bench["avg_age"].notna()].copy()
    if not scat.empty:
        chart = (alt.Chart(scat).mark_circle(opacity=0.7)
                 .encode(x=alt.X("afm_total_fleet",
                                 title="Total fleet (AFM)",
                                 scale=alt.Scale(type="log")),
                         y=alt.Y("avg_age", title="Average fleet age (yrs)"),
                         size=alt.Size("opensky_registered_fleet",
                                       title="Registered fleet"),
                         color=alt.Color("region", title="Region"),
                         tooltip=["airline_name", "icao_code",
                                  "afm_total_fleet", "avg_age",
                                  "opensky_registered_fleet", "region"])
                 .properties(title="Fleet scale vs fleet age "
                             "(log scale on fleet size)", height=460))
        st.altair_chart(chart, use_container_width=True)
        st.markdown("**Quadrants:** Large fleet + young = scale with renewal "
                    "· Large fleet + aging = replacement pressure at scale · "
                    "Small fleet + young = nimble, modern · Small fleet + "
                    "aging = vulnerable without orders.")
    st.subheader("Order-to-Fleet Ratio")
    na_panel("N/A — Data unavailable",
             "Order-to-fleet ratio needs an order-book source. It is the "
             "key expansion signal for this page and is currently missing.")
    st.subheader("Widebody Share by Airline (Skylink airborne snapshot)")
    sk = f[f["source"] == "skylink"].copy()
    sk = sk[sk["airline_id"] != "UNKNOWN"]
    wb = (sk.groupby("airline_id").apply(
        lambda g: pd.Series({
            "widebody_share": round(
                100 * g[g["body_type"] == "Widebody"]["count"].sum()
                / g["count"].sum(), 1),
            "aircraft": int(g["count"].sum())}),
        include_groups=False).reset_index())
    wb = wb.sort_values("widebody_share", ascending=False).head(10)
    if not wb.empty:
        bar_h(wb.rename(columns={"widebody_share": "Widebody %"}),
              "Widebody %", "airline_id",
              "Top 10 airlines by widebody share (Skylink airborne)")
    st.subheader("Manufacturer Dependency (Skylink airborne snapshot)")
    dep = (sk.groupby(["airline_id", "manufacturer"])["count"].sum()
           .unstack(fill_value=0).reset_index())
    for col in ("Airbus", "Boeing"):
        if col not in dep.columns:
            dep[col] = 0
    dep["total"] = dep[["Airbus", "Boeing"]].sum(axis=1)
    dep = dep[dep["total"] > 0].copy()
    dep["Airbus %"] = (100 * dep["Airbus"] / dep["total"]).round(1)
    dep = dep.sort_values("Airbus %", ascending=False).head(10)
    bar_h(dep[["airline_id", "Airbus %"]], "Airbus %", "airline_id",
          "Airbus dependency — % of Airbus+Boeing that is Airbus (Skylink)")
    st.markdown('<p class="def">A 100% Airbus share means a single-'
                'manufacturer fleet on the Airbus+Boeing subset; a 50% share '
                'is a balanced mix. Embraer/ATR/regional aircraft are '
                'excluded from this particular dependency view.</p>',
                unsafe_allow_html=True)


# ============================================================ PAGE 6
def page_quality():
    st.title("DATA QUALITY & SOURCES")
    st.caption("What is trustworthy, what is partial, and what is missing · "
               "snapshot " + SNAPSHOT)
    dq = model["dq"]
    high = int((dq["severity"] == "HIGH").sum())
    med = int((dq["severity"] == "MEDIUM").sum())
    low = int((dq["severity"] == "LOW").sum())
    c = st.columns(3)
    with c[0]:
        kpi_card("HIGH severity issues", f"{high}",
                 "Includes missing order/history/utilization sources")
    with c[1]:
        kpi_card("MEDIUM severity issues", f"{med}",
                 "Partial coverage, blank fields, naming variants")
    with c[2]:
        kpi_card("LOW severity issues", f"{low}",
                 "Minor gaps and cosmetic naming issues")
    st.subheader("Data Quality Status")
    st.dataframe(dq, use_container_width=True, hide_index=True)
    st.subheader("Source Registry")
    st.dataframe(model["registry"], use_container_width=True, hide_index=True)
    st.subheader("Definitions — do not combine without explaining")
    st.markdown("""
- **Total Fleet** — all aircraft attributed to the airline in the source.
- **Active Fleet** — in-service aircraft. AFM reports active = total because
  its idle/stored columns are 0 (flagged in Data Quality).
- **Owned / Leased / Stored Fleet** — not available in any connected source.
- **Aircraft on Order / Firm Orders / Options** — not available; no order
  source connected.
- **Retired Aircraft** — not available; no history source connected.
- **Widebody** — twin-aisle (B747/B767/B777/B787/A330/A340/A350/A380/A300).
- **Narrowbody** — single-aisle (A320 family, B737 family, A220, B757, MD-80).
- **Regional Aircraft** — E-Jets, ATR, CRJ, Dash 8, Saab 340, Twin Otter.
""")
    st.subheader("Export the model")
    for name in ("DIM_AIRLINE.csv", "DIM_AIRCRAFT.csv",
                 "FACT_FLEET_SNAPSHOT.csv", "DATA_QUALITY.csv",
                 "SOURCE_REGISTRY.csv", "FACT_FLEET_HISTORY_WEEKLY.csv",
                 "WEEKLY_CHANGES.csv"):
        path = kpis.MODEL / name
        if not path.exists():
            continue  # WEEKLY_CHANGES appears only once a change is found
        st.download_button(f"Download {name}", path.read_bytes(),
                           file_name=name, mime="text/csv")
    st.subheader("Adding airlines / aircraft types / refreshing data")
    st.markdown("""
- **Add an airline:** add its row to the AFM pull (or the OpenSky operator
  list), then re-run `python3 build_model.py`. The dashboard reads the model
  files — no app change is needed.
- **Add an aircraft type:** add its typecode to the `FAMILY` /
  `MFR_EXPLICIT` maps in `build_model.py` if the rule-based classifier gets
  its family, manufacturer or body type wrong, then re-run the build.
- **Refresh data:** re-run the four fleet pipelines (AFM weekly, OpenSky
  monthly, AirLabs monthly, Skylink weekly), copy the new CSVs into
  `../data/`, re-run `build_model.py`, and redeploy. See README.md.
""")


# ============================================================ dispatch
{"1": page_overview, "2": page_composition, "3": page_age,
 "4": page_future, "5": page_benchmark, "6": page_quality}[page[0]]()
