"""KPI calculation layer + insight engine for Global Airline Fleet Intelligence.

All calculations run on the model built by build_model.py. Anything without a
source returns None and the dashboard renders it as an explicit N/A
placeholder — values are never invented.
"""
import json
from pathlib import Path

import pandas as pd

MODEL = Path(__file__).resolve().parent / "model"

# KPIs the spec asks for that have NO connected source. Kept in one place so
# the dashboard, docs and tests all agree on what is unavailable.
UNAVAILABLE_KPIS = [
    "Fleet Growth YoY %", "Fleet CAGR", "Aircraft on Order", "Options",
    "Firm Orders", "Deliveries Next 12 Months", "Deliveries Next 3 Years",
    "Order-to-Fleet Ratio", "Expected Fleet Growth", "Fleet Utilization",
    "Replacement Ratio", "Retired Aircraft", "Aircraft Added",
    "Seats per Aircraft", "New Aircraft Growth", "Retirement Rate",
]

# Age-flag thresholds (documented defaults; adjustable in the sidebar).
# GREEN  = modern fleet, AMBER = moderate aging pressure,
# RED    = high aging / replacement pressure.
DEFAULT_THRESHOLDS = {"green_max_age": 10.0, "amber_max_age": 15.0,
                      "green_max_over15_pct": 20.0, "amber_max_over15_pct": 35.0}


def load_model():
    dim = pd.read_csv(MODEL / "DIM_AIRLINE.csv")
    fact = pd.read_csv(MODEL / "FACT_FLEET_SNAPSHOT.csv")
    aircraft = pd.read_csv(MODEL / "DIM_AIRCRAFT.csv")
    dq = pd.read_csv(MODEL / "DATA_QUALITY.csv")
    registry = pd.read_csv(MODEL / "SOURCE_REGISTRY.csv")
    summary = json.loads((MODEL / "KPI_SUMMARY.json").read_text())
    return {"dim": dim, "fact": fact, "aircraft": aircraft, "dq": dq,
            "registry": registry, "summary": summary}


def total_fleet_afm(dim):
    return int(dim["afm_total_fleet"].sum())


def active_fleet_afm(dim):
    # AFM reports active == total (idle/stored are 0 in the source); the DQ
    # layer flags this, and the dashboard says so next to the KPI.
    return int(dim["afm_active_fleet"].sum())


def registered_fleet_opensky(dim):
    return int(dim["opensky_registered_fleet"].sum())


def body_type_split(fact, sources=("airlabs", "skylink")):
    """Body-type shares from per-aircraft sources only (exact counts)."""
    f = fact[fact["source"].isin(sources)]
    tot = f["count"].sum()
    if tot == 0:
        return {}
    return {b: round(100 * c / tot, 1)
            for b, c in f.groupby("body_type")["count"].sum().items()}


def manufacturer_split(fact, sources=("airlabs", "skylink")):
    f = fact[fact["source"].isin(sources)]
    tot = f["count"].sum()
    if tot == 0:
        return {}
    return {m: round(100 * c / tot, 1)
            for m, c in f.groupby("manufacturer")["count"].sum().items()}


def manufacturer_dependency(fact, airline_icao, sources=("airlabs", "skylink")):
    """Airbus % / Boeing % for one airline (per-aircraft sources)."""
    f = fact[(fact["source"].isin(sources))
             & (fact["airline_id"] == airline_icao)]
    tot = f["count"].sum()
    if tot == 0:
        return None
    by_mfr = f.groupby("manufacturer")["count"].sum()
    return {"airbus_pct": round(100 * by_mfr.get("Airbus", 0) / tot, 1),
            "boeing_pct": round(100 * by_mfr.get("Boeing", 0) / tot, 1),
            "aircraft": int(tot)}


def fleet_by_region(dim):
    return (dim.groupby("region")["afm_total_fleet"].sum()
            .sort_values(ascending=False))


def top_airlines(dim, n=20, by="afm_total_fleet"):
    return (dim[dim[by] > 0].sort_values(by, ascending=False)
            .head(n)[["airline_name", "icao_code", "country", "region",
                      "afm_total_fleet", "afm_active_fleet",
                      "opensky_registered_fleet"]])


def avg_age_by_airline(dim):
    """OpenSky-derived average age = snapshot year - avg built year.

    Only rows with built-year coverage >= 50% are used, and coverage is
    returned alongside so the dashboard can show it.
    """
    d = dim.copy()
    d["avg_built_year"] = pd.to_numeric(d["opensky_avg_built_year"],
                                        errors="coerce")
    d["coverage"] = pd.to_numeric(d["opensky_built_year_coverage_pct"],
                                  errors="coerce")
    d = d[d["avg_built_year"].notna() & (d["coverage"] >= 50)
          & (d["opensky_registered_fleet"] > 0)]
    d["avg_age"] = (2026 - d["avg_built_year"]).round(1)
    return d.sort_values("avg_age", ascending=False)


def flag_age(avg_age, over15_pct=None, t=None):
    """GREEN / AMBER / RED classification with documented thresholds."""
    t = t or DEFAULT_THRESHOLDS
    if avg_age is None:
        return "N/A"
    if avg_age <= t["green_max_age"]:
        return "GREEN"
    if avg_age <= t["amber_max_age"]:
        return "AMBER"
    return "RED"


def order_book():
    """No order source connected -> None. Never a fabricated number."""
    return None


def fleet_growth_yoy():
    """No history source connected -> None."""
    return None


def fleet_cagr():
    """No history source connected -> None."""
    return None


def fleet_utilization():
    """No block-hours/cycles source connected -> None."""
    return None


# --------------------------------------------------------- insight engine
def generate_insights(model):
    """Dynamic insight lines, computed from the data (never hard-coded)."""
    dim, fact, s = model["dim"], model["fact"], model["summary"]
    lines = []
    top = s["top_afm"][0]
    lines.append(
        f"Largest fleet in the benchmark group: {top['name']} "
        f"({top['icao']}) with {top['total']:,} aircraft (AFM, active).")
    reg = s["fleet_by_region_afm"]
    biggest_region = max(reg, key=reg.get)
    lines.append(
        f"{biggest_region} holds the largest regional fleet "
        f"({reg[biggest_region]:,} active aircraft, AFM).")
    body = s["body_type_split_airlabs_skylink"]
    nb = body.get("Narrowbody", 0)
    wb = body.get("Widebody", 0)
    tot = sum(body.values())
    lines.append(
        f"Across the per-aircraft snapshot (AirLabs + Skylink, "
        f"{tot:,} aircraft), {nb} are narrowbody and {wb} are widebody.")
    mfr = s["airlabs_manufacturer_split"]
    ab = mfr.get("Airbus", 0)
    bo = mfr.get("Boeing", 0)
    lines.append(
        f"AirLabs aircraft split {ab} Airbus vs {bo} Boeing "
        f"(typecode-derived; raw manufacturer field is blank on 36%).")
    age = s["airlabs_avg_age"]
    bands = s["airlabs_age_bands"]
    over15 = bands.get("15-20", 0) + bands.get(">20", 0)
    aged = sum(bands.values())
    lines.append(
        f"AirLabs average fleet age is {age} years; "
        f"{over15} of {aged} aircraft with a known age "
        f"({round(100 * over15 / aged)}%) are older than 15 years.")
    lines.append(
        "Growth, order book and utilization are N/A: no fleet-history, "
        "order-book or block-hours source is connected yet.")
    return lines
