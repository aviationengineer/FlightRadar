"""Build the Global Airline Fleet Intelligence data model.

Reads the four Fleet Intelligence source CSVs (snapshot 2026-11-05) and writes
the analytical model into ./model/:
  DIM_AIRLINE, DIM_AIRCRAFT, FACT_FLEET_SNAPSHOT,
  FACT_AIRCRAFT_ORDER (schema only — no order source),
  FACT_FLEET_HISTORY (schema only — single snapshot, no history),
  DATA_QUALITY, SOURCE_REGISTRY, KPI_SUMMARY.json

Rules:
- Never fabricate. Anything without a source is an explicit empty table / N/A.
- AFM avg_age 11.2 is a site-wide placeholder in 549/860 rows -> flagged LOW
  confidence, never used as a headline age without the flag.
- OpenSky counts only aircraft with a known operator (41,752 of 520,000).
- AFM idle/stored columns are 0 everywhere -> not used.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path.home() / "workspace/fleet-dashboard/data"
OUT = HERE / "model"
OUT.mkdir(parents=True, exist_ok=True)
SNAPSHOT_DATE = "2026-11-05"


def load(name):
    with open(SRC / (name + ".csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_history():
    """Weekly snapshots recorded by snapshot_weekly.py (may be empty)."""
    p = HERE.parent / "history" / "weekly_snapshots.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def wcsv(name, fieldnames, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {name}: {len(rows)} rows")


# ---------------------------------------------------------------- regions
# Simplified 6-region aviation grouping (documented in DATA_DICTIONARY.md).
REGION = {
    # North America
    "United States": "North America", "Canada": "North America",
    "Mexico": "North America", "Bahamas": "North America",
    "Barbados": "North America", "Cuba": "North America",
    "Dominican Republic": "North America", "Jamaica": "North America",
    "Haiti": "North America", "Trinidad and Tobago": "North America",
    "Antigua and Barbuda": "North America", "Aruba": "North America",
    "Cayman Islands": "North America", "American Samoa": "North America",
    # Latin America & Caribbean
    "Argentina": "Latin America", "Bolivia": "Latin America",
    "Brazil": "Latin America", "Chile": "Latin America",
    "Colombia": "Latin America", "Costa Rica": "Latin America",
    "Ecuador": "Latin America", "Panama": "Latin America",
    "Paraguay": "Latin America", "Peru": "Latin America",
    "Uruguay": "Latin America", "Venezuela": "Latin America",
    "Suriname": "Latin America", "French Guiana": "Latin America",
    # Europe
    "Albania": "Europe", "Austria": "Europe", "Belarus": "Europe",
    "Belgium": "Europe", "Bulgaria": "Europe", "Croatia": "Europe",
    "Cyprus": "Europe", "Czech Republic": "Europe", "Denmark": "Europe",
    "Estonia": "Europe", "Finland": "Europe", "France": "Europe",
    "Georgia": "Europe", "Germany": "Europe", "Greece": "Europe",
    "Hungary": "Europe", "Iceland": "Europe", "Ireland": "Europe",
    "Italy": "Europe", "Latvia": "Europe", "Lithuania": "Europe",
    "Luxembourg": "Europe", "Malta": "Europe", "Moldova": "Europe",
    "Montenegro": "Europe", "Netherlands": "Europe",
    "Netherlands Antilles": "Europe", "Norway": "Europe",
    "Poland": "Europe", "Portugal": "Europe", "Romania": "Europe",
    "Russia": "Europe", "Russian Federation": "Europe",
    "Serbia": "Europe", "Slovakia": "Europe", "Slovenia": "Europe",
    "Spain": "Europe", "Sweden": "Europe", "Switzerland": "Europe",
    "Ukraine": "Europe", "United Kingdom": "Europe",
    "Armenia": "Europe", "Azerbaijan": "Europe",
    "Faroe Islands": "Europe", "Turkey": "Europe",
    # Africa
    "Algeria": "Africa", "Angola": "Africa", "Benin": "Africa",
    "Botswana": "Africa", "Burkina Faso": "Africa", "Djibouti": "Africa",
    "Egypt": "Africa", "Equatorial Guinea": "Africa", "Eritrea": "Africa",
    "Ethiopia": "Africa", "Guinea": "Africa", "Ivory Coast": "Africa",
    "Kenya": "Africa", "Libya": "Africa", "Madagascar": "Africa",
    "Malawi": "Africa", "Mauritania": "Africa", "Mauritius": "Africa",
    "Morocco": "Africa", "Mozambique": "Africa", "Namibia": "Africa",
    "Niger": "Africa", "Nigeria": "Africa", "Rwanda": "Africa",
    "Seychelles": "Africa", "Sierra Leone": "Africa",
    "South Africa": "Africa", "Sudan": "Africa", "Tanzania": "Africa",
    "Togo": "Africa", "Tunisia": "Africa", "Zimbabwe": "Africa",
    "Republic of the Congo": "Africa", "Reunion": "Africa",
    # Middle East
    "Iran": "Middle East", "Iraq": "Middle East", "Israel": "Middle East",
    "Jordan": "Middle East", "Kuwait": "Middle East",
    "Lebanon": "Middle East", "Oman": "Middle East", "Qatar": "Middle East",
    "Saudi Arabia": "Middle East", "Syrian Arab Republic": "Middle East",
    "United Arab Emirates": "Middle East", "Yemen": "Middle East",
    # Asia-Pacific
    "Afghanistan": "Asia-Pacific", "Bangladesh": "Asia-Pacific",
    "Bhutan": "Asia-Pacific", "Brunei": "Asia-Pacific",
    "Cambodia": "Asia-Pacific", "China": "Asia-Pacific",
    "Hong Kong SAR of China": "Asia-Pacific", "India": "Asia-Pacific",
    "Indonesia": "Asia-Pacific", "Japan": "Asia-Pacific",
    "Lao Peoples Democratic Republic": "Asia-Pacific",
    "Macao": "Asia-Pacific", "Malaysia": "Asia-Pacific",
    "Maldives": "Asia-Pacific", "Myanmar": "Asia-Pacific",
    "Burma": "Asia-Pacific", "Nepal": "Asia-Pacific",
    "Pakistan": "Asia-Pacific", "Philippines": "Asia-Pacific",
    "Republic of Korea": "Asia-Pacific", "South Korea": "Asia-Pacific",
    "Singapore": "Asia-Pacific", "Sri Lanka": "Asia-Pacific",
    "Taiwan": "Asia-Pacific", "Thailand": "Asia-Pacific",
    "Vietnam": "Asia-Pacific", "Australia": "Asia-Pacific",
    "Fiji": "Asia-Pacific", "Kiribati": "Asia-Pacific",
    "Marshall Islands": "Asia-Pacific", "New Zealand": "Asia-Pacific",
    "Papua New Guinea": "Asia-Pacific", "Solomon Islands": "Asia-Pacific",
    "Vanuatu": "Asia-Pacific", "French Polynesia": "Asia-Pacific",
    "Cook Islands": "Asia-Pacific", "Kazakhstan": "Asia-Pacific",
    "Kyrgyzstan": "Asia-Pacific", "Mongolia": "Asia-Pacific",
    "Uzbekistan": "Asia-Pacific", "Turkmenistan": "Asia-Pacific",
    "Democratic People's Republic of Korea": "Asia-Pacific",
}

# ------------------------------------------------- typecode classification
# Explicit family overrides first; fallback rules below. Body types:
# widebody / narrowbody / regional / other (general aviation, helicopter).
FAMILY = {
    "A318": "A320 family", "A319": "A320 family", "A320": "A320 family",
    "A321": "A320 family", "A20N": "A320 family", "A21N": "A320 family",
    "B733": "B737 family", "B734": "B737 family", "B735": "B737 family",
    "B736": "B737 family", "B737": "B737 family", "B738": "B737 family",
    "B739": "B737 family", "B73G": "B737 family", "B38M": "B737 family",
    "B39M": "B737 family",
    "B744": "B747 family", "B748": "B747 family", "B74S": "B747 family",
    "B752": "B757 family", "B753": "B757 family",
    "B762": "B767 family", "B763": "B767 family",
    "B772": "B777 family", "B773": "B777 family", "B77W": "B777 family",
    "B77L": "B777 family", "B778": "B777 family", "B779": "B777 family",
    "B788": "B787 family", "B789": "B787 family", "B78X": "B787 family",
    "A332": "A330 family", "A333": "A330 family", "A339": "A330 family",
    "A342": "A340 family", "A343": "A340 family",
    "A359": "A350 family", "A35K": "A350 family",
    "A388": "A380 family", "A38F": "A380 family",
    "BCS1": "A220 family", "BCS3": "A220 family",
    "E170": "E-Jets", "E175": "E-Jets", "E190": "E-Jets",
    "E195": "E-Jets", "E290": "E-Jets", "E295": "E-Jets",
    "E145": "ERJ family", "E135": "ERJ family", "E140": "ERJ family",
    "AT43": "ATR family", "AT45": "ATR family", "AT72": "ATR family",
    "AT76": "ATR family",
    "CRJ1": "CRJ family", "CRJ2": "CRJ family", "CRJ7": "CRJ family",
    "CRJ9": "CRJ family", "CRJX": "CRJ family",
    "DH8A": "Dash 8 family", "DH8B": "Dash 8 family",
    "DH8C": "Dash 8 family", "DH8D": "Dash 8 family",
    "MD11": "MD-11", "MD80": "MD-80 family", "MD82": "MD-80 family",
    "MD83": "MD-80 family", "MD88": "MD-80 family", "MD90": "MD-90",
    "A306": "A300 family", "A30B": "A300 family", "A310": "A310 family",
    "B190": "Beech 1900", "BE20": "King Air", "C208": "Cessna Caravan",
    "C172": "Cessna 172", "PC12": "Pilatus PC-12",
    "C56X": "Cessna Citation", "C25A": "Cessna Citation",
    "SU95": "SSJ100", "C919": "C919",
    "E75L": "E-Jets", "E75S": "E-Jets",
    "SF34": "Saab 340", "DHC6": "Twin Otter", "F100": "Fokker 100",
    "E55P": "Phenom 300", "E45X": "Legacy 450", "B350": "King Air 350",
    "C130": "C-130", "C17": "C-17", "A10": "A-10", "F16": "F-16",
    "EUFI": "Eurofighter Typhoon", "TOR": "Tornado", "HAWK": "BAE Hawk",
    "LYNX": "Lynx", "H47": "Chinook", "AN2": "An-2", "AN32": "An-32",
    "CL60": "Challenger 600", "CL30": "Challenger 300", "C402": "Cessna 402",
    "SR22": "Cirrus SR22", "FA50": "Falcon 50", "FA7X": "Falcon 7X",
    "C750": "Citation X", "PA44": "Piper Seminole", "R22": "Robinson R22",
    "A119": "AW119", "S92": "S-92", "BE9L": "King Air 90",
    "TEX2": "T-6 Texan", "MI8": "Mi-8", "AS50": "AS350",
    "GLEX": "Global Express", "P28A": "Piper PA-28",
}
# Explicit manufacturer overrides (military, regional and GA types where
# the typecode prefix alone is ambiguous).
MFR_EXPLICIT = {
    "B38M": "Boeing", "B39M": "Boeing", "B350": "Beechcraft",
    "TEX2": "Beechcraft", "E75L": "Embraer", "E75S": "Embraer",
    "E55P": "Embraer", "E45X": "Embraer", "SF34": "Saab",
    "DHC6": "De Havilland Canada", "F100": "Fokker",
    "F16": "Lockheed Martin", "F22": "Lockheed Martin",
    "F35": "Lockheed Martin", "F15": "Boeing", "F18": "Boeing",
    "EUFI": "Eurofighter", "TOR": "Panavia", "HAWK": "BAE Systems",
    "LYNX": "Leonardo", "A10": "Fairchild Republic", "H47": "Boeing",
    "C130": "Lockheed Martin", "C17": "Boeing", "K35R": "Boeing",
    "CL60": "Bombardier", "CL30": "Bombardier", "C402": "Cessna",
    "SR22": "Cirrus", "FA50": "Dassault", "FA7X": "Dassault",
    "C750": "Cessna", "PA44": "Piper", "R22": "Robinson",
    "A119": "Leonardo", "S92": "Sikorsky", "BE20": "Beechcraft",
    "BE9L": "Beechcraft", "B190": "Beechcraft",
}
WIDEBODY_TYPES = {
    "B744", "B748", "B74S", "B762", "B763", "B772", "B773", "B77W", "B77L",
    "B778", "B779", "B788", "B789", "B78X", "A332", "A333", "A339", "A342",
    "A343", "A359", "A35K", "A388", "A38F", "A306", "A30B", "A310", "MD11",
}
REGIONAL_TYPES = {
    "E170", "E175", "E190", "E195", "E290", "E295", "E145", "E135", "E140",
    "E75L", "E75S",
    "AT43", "AT45", "AT72", "AT76", "CRJ1", "CRJ2", "CRJ7", "CRJ9", "CRJX",
    "DH8A", "DH8B", "DH8C", "DH8D", "B190", "SU95",
    "SF34", "DHC6", "AN2", "AN32", "AN24", "AN26",
}
MILITARY_TYPES = {
    "F16", "F15", "F18", "F22", "F35", "EUFI", "TOR", "HAWK", "LYNX",
    "A10", "H47", "K35R", "C130", "C17", "TEX2", "MI8", "AS50",
}
# Business jets / light GA types that are neither narrowbody nor regional.
BUSINESS_JET_TYPES = {
    "CL60", "CL30", "FA50", "FA7X", "SR22", "PA44", "R22", "A119", "S92",
    "BE20", "BE9L",
}


def classify_typecode(tc):
    """Return (family, manufacturer, body_type) for an ICAO typecode."""
    tc = (tc or "").strip().upper()
    if not tc or tc == "UNKNOWN":
        return ("Unknown", "Unknown", "Other")
    family = FAMILY.get(tc, tc)
    if tc in MFR_EXPLICIT:
        mfr = MFR_EXPLICIT[tc]
    elif tc.startswith("A3") or tc in ("A20N", "A21N", "A306", "A30B", "A310",
                                     "BCS1", "BCS3"):
        mfr = "Airbus"
    elif tc.startswith("B7") or tc.startswith("B3"):
        mfr = "Boeing"
    elif tc.startswith(("E1", "E2", "E4", "E5", "E7")):
        mfr = "Embraer"
    elif tc.startswith("AT"):
        mfr = "ATR"
    elif tc.startswith("CRJ"):
        mfr = "Bombardier"
    elif tc.startswith("DH8"):
        mfr = "De Havilland Canada"
    elif tc.startswith("AN"):
        mfr = "Antonov"
    elif tc.startswith("SF"):
        mfr = "Saab"
    elif tc.startswith("DHC"):
        mfr = "De Havilland Canada"
    elif tc.startswith("C1") or tc.startswith("C2") or tc.startswith("C5"):
        mfr = "Cessna"
    elif tc.startswith("PC"):
        mfr = "Pilatus"
    elif tc.startswith("P2"):
        mfr = "Piper"
    elif tc.startswith("MI"):
        mfr = "Mil"
    elif tc.startswith("AS"):
        mfr = "Airbus Helicopters"
    elif tc.startswith("GL"):
        mfr = "Gulfstream"
    elif tc.startswith("SU"):
        mfr = "Sukhoi"
    elif tc.startswith("C9"):
        mfr = "COMAC"
    elif tc.startswith("MD"):
        mfr = "McDonnell Douglas"
    elif tc.startswith("K3") or tc.startswith("C1") and tc[1] == "3":
        mfr = "Boeing"
    else:
        mfr = "Unknown"
    if tc in WIDEBODY_TYPES:
        body = "Widebody"
    elif tc in REGIONAL_TYPES:
        body = "Regional"
    elif tc in MILITARY_TYPES:
        body = "Other"
    elif tc in BUSINESS_JET_TYPES:
        body = "Other"
    elif mfr in ("Cessna", "Beechcraft", "Pilatus", "Piper", "Mil",
                 "Airbus Helicopters", "Gulfstream"):
        body = "Other"
    elif tc.startswith(("C1", "C2", "C5", "TEX", "K35", "C13", "C17",
                        "A10", "P28")):
        body = "Other"
    else:
        body = "Narrowbody"
    return (family, mfr, body)


STOP_WORDS = {"BOEING", "AIRBUS", "BOMBARDIER", "INC", "CANADA", "LP",
              "S", "A", "SAS", "COMPANY", "THE"}


def extract_typecode(raw):
    """Pull an ICAO typecode out of a messy aircraft_type string."""
    if not raw:
        return "UNKNOWN"
    tokens = re.findall(r"[A-Za-z0-9]+", raw.upper())
    cands = [t for t in tokens if t not in STOP_WORDS and 3 <= len(t) <= 4
             and re.match(r"^[A-Z][A-Z0-9]{2,3}$", t)]
    return cands[-1] if cands else "UNKNOWN"


# ------------------------------------------------------------------ load
afm = load("AFM_Fleets")
opensky = load("OPENSKY_Counts")
airlabs = load("AIRLABS_Fleets")
skylink = load("SKYLINK_Fleets")
catalog = load("Fleet_Catalog")

# ------------------------------------------------------------- DIM_AIRLINE
# AFM is the airline spine (name + country); OpenSky adds registered counts.
afm_by_icao = {}
for r in afm:
    icao = (r.get("icao") or "").strip().upper()
    if icao:
        afm_by_icao[icao] = r

osk_by_key = {}
for r in opensky:
    icao = (r.get("operator_icao") or "").strip().upper()
    # 51 operators have no ICAO code (e.g. Thai Lion Air, Peach Aviation);
    # key them by their stable operator_key (e.g. "IATA:SL") instead.
    key = icao or (r.get("operator_key") or "").strip()
    if key:
        osk_by_key[key] = r


def osk_key(r):
    icao = (r.get("operator_icao") or "").strip().upper()
    return icao or (r.get("operator_key") or "").strip()

# Skylink airborne by operator: callsign prefix (first 3 letters) ~= ICAO.
sk_by_icao = Counter()
for r in skylink:
    cs = (r.get("callsign") or "").strip().upper()
    if len(cs) >= 3 and cs[:3].isalpha():
        sk_by_icao[cs[:3]] += 1

al_by_icao = Counter()
for r in airlabs:
    icao = (r.get("airline_icao") or "").strip().upper()
    if icao:
        al_by_icao[icao] += 1

all_icao = sorted(set(afm_by_icao) | set(osk_by_key))
dim_airline = []
for key in all_icao:
    a = afm_by_icao.get(key)
    o = osk_by_key.get(key)
    name = (a or {}).get("airline") or (o or {}).get("operator_name") or key
    country = (a or {}).get("country") or ""
    region = REGION.get(country, "Unknown") if country else "Unknown"
    afm_total = int(num((a or {}).get("total"))) if a else 0
    afm_active = int(num((a or {}).get("active"))) if a else 0
    osk_total = int(num((o or {}).get("total_fleet"))) if o else 0
    afm_age = num((a or {}).get("average_age")) if a else None
    dim_airline.append({
        "airline_id": key,
        "airline_name": name,
        "iata_code": (a or {}).get("iata") or (o or {}).get("operator_iata") or "",
        "icao_code": key if (a or o) and len(key) == 3 and key.isalpha() else
                     ((a or {}).get("icao") or (o or {}).get("operator_icao") or ""),
        "country": country,
        "region": region,
        "airline_group": "",
        "business_model": "",
        "afm_total_fleet": afm_total,
        "afm_active_fleet": afm_active,
        "opensky_registered_fleet": osk_total,
        "skylink_airborne": sk_by_icao.get(key, 0),
        "airlabs_aircraft": al_by_icao.get(key, 0),
        "afm_avg_age": (f"{afm_age:.1f}" if afm_age else ""),
        "opensky_avg_built_year": (o or {}).get("avg_built_year") or "",
        "opensky_built_year_coverage_pct":
            (o or {}).get("built_year_coverage_pct") or "",
        "in_afm": "Y" if a else "N",
        "in_opensky": "Y" if o else "N",
    })

wcsv("DIM_AIRLINE.csv", list(dim_airline[0].keys()), dim_airline)

# ------------------------------------------------------------ DIM_AIRCRAFT
typecodes = set()
for r in opensky:
    for t in (r.get("top_types_summary") or "").split(";"):
        tc = t.split(":")[0].strip().upper()
        if tc and tc != "UNKNOWN":
            typecodes.add(tc)
for r in airlabs:
    tc = (r.get("icao_type") or "").strip().upper()
    if tc:
        typecodes.add(tc)
for r in skylink:
    tc = extract_typecode(r.get("aircraft_type"))
    if tc != "UNKNOWN":
        typecodes.add(tc)

dim_aircraft = []
for tc in sorted(typecodes):
    fam, mfr, body = classify_typecode(tc)
    dim_aircraft.append({
        "aircraft_id": tc, "aircraft_type": tc, "aircraft_family": fam,
        "manufacturer": mfr, "body_type": body, "engine_family": "",
        "seat_capacity": "",
    })
wcsv("DIM_AIRCRAFT.csv", list(dim_aircraft[0].keys()), dim_aircraft)

# ------------------------------------------------------ FACT_FLEET_SNAPSHOT
fact = []


def add_fact(source, icao, name, tc, count, status, avg_age=None,
             age_cov=""):
    fam, mfr, body = classify_typecode(tc)
    fact.append({
        "snapshot_date": SNAPSHOT_DATE, "source": source,
        "airline_id": icao, "airline_name": name, "aircraft_type": tc,
        "aircraft_family": fam, "manufacturer": mfr, "body_type": body,
        "fleet_status": status, "count": count,
        "avg_age_years": (f"{avg_age:.1f}" if avg_age is not None else ""),
        "age_coverage_pct": age_cov,
    })


# (a) OpenSky: top-5 types per operator + residual row.
for r in opensky:
    key = osk_key(r)
    icao = key
    total = int(num(r.get("total_fleet")))
    seen = 0
    for t in (r.get("top_types_summary") or "").split(";"):
        parts = t.strip().split(":")
        if len(parts) != 2:
            continue
        tc, cnt = parts[0].strip().upper(), int(num(parts[1]))
        if not tc or tc == "UNKNOWN":
            continue
        seen += cnt
        add_fact("opensky", key, r.get("operator_name"), tc, cnt, "registered",
                 avg_age=None, age_cov=r.get("built_year_coverage_pct") or "")
    if total - seen > 0:
        add_fact("opensky", key, r.get("operator_name"), "OTHER",
                 total - seen, "registered",
                 age_cov=r.get("built_year_coverage_pct") or "")

# (b) AirLabs: per-aircraft rows aggregated by airline+type, with real ages.
al_agg = defaultdict(list)
for r in airlabs:
    icao = (r.get("airline_icao") or "").strip().upper() or "UNKNOWN"
    tc = (r.get("icao_type") or "").strip().upper() or "UNKNOWN"
    al_agg[(icao, tc)].append(num(r.get("age")))
for (icao, tc), all_ages in sorted(al_agg.items()):
    ages = [a for a in all_ages if a > 0]
    add_fact("airlabs", icao, "", tc, len(all_ages), "in_service",
             avg_age=(sum(ages) / len(ages) if ages else None),
             age_cov=(f"{100 * len(ages) / len(all_ages):.0f}"
                      if all_ages else "0"))

# (c) Skylink: per-aircraft rows aggregated by callsign prefix + type.
sk_agg = Counter()
for r in skylink:
    cs = (r.get("callsign") or "").strip().upper()
    icao = cs[:3] if len(cs) >= 3 and cs[:3].isalpha() else "UNKNOWN"
    sk_agg[(icao, extract_typecode(r.get("aircraft_type")))] += 1
for (icao, tc), cnt in sorted(sk_agg.items()):
    add_fact("skylink", icao, "", tc, cnt, "airborne")

# (d) AFM: one aggregate row per airline (active fleet total).
for r in afm:
    icao = (r.get("icao") or "").strip().upper()
    if not icao:
        continue
    add_fact("afm", icao, r.get("airline"), "ALL", int(num(r.get("total"))),
             "active")

wcsv("FACT_FLEET_SNAPSHOT.csv", list(fact[0].keys()), fact)

# --------------------------------- FACT_AIRCRAFT_ORDER / FACT_FLEET_HISTORY
# No order source, and no full year of history: schema only, zero rows. The
# dashboard renders these pages as explicit N/A placeholders, never
# fabricated values. Week-over-week history lives in
# FACT_FLEET_HISTORY_WEEKLY.csv (populated by snapshot_weekly.py, never by
# this builder); this yearly file stays empty until 12 months of weekly
# snapshots exist.
wcsv("FACT_AIRCRAFT_ORDER.csv",
     ["airline_id", "aircraft_family", "manufacturer", "order_status",
      "order_quantity", "delivery_year", "delivery_month",
      "firm_order_flag", "option_flag"], [])
wcsv("FACT_FLEET_HISTORY.csv",
     ["airline_id", "year", "fleet_count", "active_fleet",
      "retired_aircraft", "new_deliveries"], [])

# ------------------------------------------------------------- DATA QUALITY
dq = []


def dq_row(source, check, severity, affected, total, detail):
    dq.append({"source": source, "check": check, "severity": severity,
               "affected_records": affected, "total_records": total,
               "detail": detail})


# AFM checks
placeholder_age = sum(1 for r in afm
                      if abs(num(r.get("average_age")) - 11.2) < 0.01)
dq_row("afm", "avg_age is site-wide placeholder (11.2)", "HIGH",
       placeholder_age, len(afm),
       "549 of 860 airlines share exactly 11.2; do not use as headline age")
dq_row("afm", "idle/stored columns are 0 for all rows", "HIGH",
       len(afm), len(afm), "idle_7_29d and stored_30d_plus are 0 everywhere")
dq_row("afm", "country value is not a country (ALASKA/AVIANCA/DRAGON/S.A./"
       "International)", "MEDIUM",
       sum(1 for r in afm if (r.get("country") or "") in
           ("ALASKA", "AVIANCA", "DRAGON", "S.A.", "International")),
       len(afm), "rows carry a non-country value in the country field")
dq_row("afm", "missing ICAO code", "MEDIUM",
       sum(1 for r in afm if not (r.get("icao") or "").strip()), len(afm), "")
dq_row("afm", "ICAO code is not 3 letters (e.g. FI5, AI0, 99F, ...)",
       "MEDIUM",
       sum(1 for r in afm
           if (r.get("icao") or "").strip()
           and not re.match(r"^[A-Z]{3}$", (r.get("icao") or "").strip())),
       len(afm), "AFM's icao field mixes designators and internal codes; "
       "join keys on these rows are unreliable")
dq_row("afm", "airline name is a placeholder ('...')", "LOW",
       sum(1 for r in afm if (r.get("airline") or "").strip() == "..."),
       len(afm), "one row carries no usable airline name")
dq_row("afm", "duplicate country naming (Russia / Russian Federation; "
       "South Korea / Republic of Korea; Burma / Myanmar)", "LOW", 0,
       len(afm), "same country under two names; region mapping normalises")

# OpenSky checks
dq_row("opensky", "aircraft with no known operator (excluded from counts)",
       "HIGH", 520000 - 41752, 520000,
       "only 41,752 of ~520,000 aircraft have operatoricao; counts are the "
       "known-operator subset")
dq_row("opensky", "missing built year (age coverage)", "MEDIUM",
       41752 - int(41752 * 0.312), 41752,
       "built-year coverage is 31.2% overall; US carriers 80-95%, "
       "Chinese/European 0-1%")
dq_row("opensky", "operator with no ICAO code (keyed by operator_key)",
       "MEDIUM",
       sum(1 for r in opensky if not (r.get("operator_icao") or "").strip()),
       len(opensky), "51 operators (345 aircraft) incl. Thai Lion Air, "
       "Peach Aviation, Thai Smile; keyed by IATA operator_key instead")
dq_row("opensky", "operator with UNKNOWN top typecode", "LOW",
       sum(1 for r in opensky if r.get("top_typecode") == "UNKNOWN"),
       len(opensky), "")

# AirLabs checks
dq_row("airlabs", "partial snapshot (quota exhausted, 650 of ~25k expected)",
       "HIGH", 0, 650, "November quota spent before the run; December reset "
       "will show whether the dataset genuinely ends at 650")
dq_row("airlabs", "airline name blank", "MEDIUM",
       sum(1 for r in airlabs if not (r.get("airline") or "").strip()),
       len(airlabs), "649 rows carry no airline name")
dq_row("airlabs", "missing aircraft type (icao_type blank)", "HIGH",
       sum(1 for r in airlabs if not (r.get("icao_type") or "").strip()),
       len(airlabs), "233 of 649 rows carry no typecode; manufacturer and "
       "body type cannot be derived for these rows")
dq_row("airlabs", "missing manufacturer (raw field)", "MEDIUM",
       sum(1 for r in airlabs if not (r.get("manufacturer") or "").strip()),
       len(airlabs), "233 of 649 rows blank; dashboard derives manufacturer "
       "from the ICAO typecode instead")
dq_row("airlabs", "missing age", "LOW",
       sum(1 for r in airlabs if not (r.get("age") or "").strip()),
       len(airlabs), "")

# Skylink checks
dq_row("skylink", "manufacturer blank", "MEDIUM",
       sum(1 for r in skylink if not (r.get("manufacturer") or "").strip()),
       len(skylink), "737 of 762 rows; derive manufacturer from typecode")
dq_row("skylink", "aircraft model blank", "LOW",
       sum(1 for r in skylink if not (r.get("model") or "").strip()),
       len(skylink), "")
dq_row("skylink", "operator blank (derive from callsign prefix)", "LOW",
       sum(1 for r in skylink if not (r.get("operator") or "").strip()),
       len(skylink), "")

# Cross-source
dq_row("all", "no order-book source connected", "HIGH", 0, 0,
       "FACT_AIRCRAFT_ORDER is empty; order KPIs render N/A")
hist_dates = sorted({r.get("snapshot_date", "") for r in read_history()}
                    - {""})
if hist_dates:
    dq_row("all", "fleet history is weekly only (no YoY yet)", "MEDIUM",
           0, 0,
           f"weekly snapshots since {hist_dates[0]} ({len(hist_dates)}); "
           "growth YoY/CAGR need 12 months of snapshots")
else:
    dq_row("all", "no fleet history source connected", "HIGH", 0, 0,
           "FACT_FLEET_HISTORY is empty; growth/CAGR KPIs render N/A")
dq_row("all", "no utilization source connected (block hours / cycles)",
       "HIGH", 0, 0, "fleet_status does not carry block hours or cycles")
wcsv("DATA_QUALITY.csv", list(dq[0].keys()), dq)

# ---------------------------------------------------------- SOURCE REGISTRY
reg = []
for r in catalog:
    reg.append({
        "source_name": r.get("source"), "source_url": "",
        "source_date": r.get("snapshot_date") or SNAPSHOT_DATE,
        "retrieval_date": SNAPSHOT_DATE,
        "data_confidence": ("LOW" if r.get("source") == "airlabs"
                            else "MEDIUM"),
        "record_count": r.get("rows") or "",
        "coverage": r.get("coverage") or "",
        "status": r.get("status") or "",
    })
reg.append({"source_name": "afm_site_snapshot", "source_url":
            "https://airlinefleetmonitor.com/data/airlines.json",
            "source_date": "2026-09-17", "retrieval_date": SNAPSHOT_DATE,
            "data_confidence": "MEDIUM", "record_count": "860",
            "coverage": "860 active airlines; 25,226 airframes",
            "status": "LIVE"})
reg.append({"source_name": "opensky_aircraft_database", "source_url":
            "https://opensky-network.org/datasets/metadata/",
            "source_date": SNAPSHOT_DATE, "retrieval_date": SNAPSHOT_DATE,
            "data_confidence": "HIGH", "record_count": "520000",
            "coverage": "41,752 aircraft with known operator",
            "status": "LIVE"})
wcsv("SOURCE_REGISTRY.csv", list(reg[0].keys()), reg)

# ------------------------------------------------------------- KPI SUMMARY
afm_tot = sum(int(num(r.get("total"))) for r in afm)
afm_act = sum(int(num(r.get("active"))) for r in afm)
osk_tot = sum(int(num(r.get("total_fleet"))) for r in opensky)
al_ages = [num(r.get("age")) for r in airlabs if num(r.get("age")) > 0]
# Manufacturer split from the typecode-derived classification in the fact
# table (the raw AirLabs manufacturer field is blank on 233/649 rows).
al_mfr = Counter()
for row in fact:
    if row["source"] == "airlabs":
        al_mfr[row["manufacturer"]] += row["count"]
# Manufacturer split from OpenSky top-type counts (partial coverage).
osk_mfr = Counter()
for r in opensky:
    for t in (r.get("top_types_summary") or "").split(";"):
        parts = t.strip().split(":")
        if len(parts) != 2:
            continue
        tc, cnt = parts[0].strip().upper(), int(num(parts[1]))
        if tc and tc != "UNKNOWN":
            osk_mfr[classify_typecode(tc)[1]] += cnt
body = Counter()
for row in fact:
    if row["source"] in ("airlabs", "skylink"):
        body[row["body_type"]] += row["count"]
region_tot = Counter()
for d in dim_airline:
    region_tot[d["region"]] += d["afm_total_fleet"]
top_afm = sorted(dim_airline, key=lambda d: -d["afm_total_fleet"])[:10]
top_osk = sorted(dim_airline, key=lambda d: -d["opensky_registered_fleet"])[:10]
age_bands = Counter()
for a in al_ages:
    age_bands["<5" if a < 5 else "5-10" if a < 10 else "10-15"
              if a < 15 else "15-20" if a < 20 else ">20"] += 1

if hist_dates:
    unavail_reason = (f"Weekly fleet history started {hist_dates[0]} "
                      f"({len(hist_dates)} snapshot(s)); growth YoY/CAGR "
                      "need 12 months of snapshots. No order-book or "
                      "utilization source is connected.")
else:
    unavail_reason = ("No order-book, fleet-history, or utilization "
                      "source is connected. FACT_AIRCRAFT_ORDER and "
                      "FACT_FLEET_HISTORY are empty by design.")

summary = {
    "snapshot_date": SNAPSHOT_DATE,
    "weekly_history": {"first_snapshot": hist_dates[0] if hist_dates else None,
                       "snapshots": len(hist_dates)},
    "total_fleet_afm": afm_tot,
    "active_fleet_afm": afm_act,
    "registered_fleet_opensky": osk_tot,
    "airlines_afm": len(afm),
    "operators_opensky": len(opensky),
    "airlabs_aircraft": len(airlabs),
    "skylink_airborne": len(skylink),
    "icao_overlap_afm_opensky": len(set(afm_by_icao) & set(osk_by_key)),
    "airlabs_avg_age": round(sum(al_ages) / len(al_ages), 1) if al_ages else None,
    "airlabs_age_bands": dict(age_bands),
    "airlabs_manufacturer_split": dict(al_mfr),
    "opensky_manufacturer_split_top_types": dict(osk_mfr),
    "body_type_split_airlabs_skylink": dict(body),
    "fleet_by_region_afm": dict(region_tot),
    "top_afm": [{"icao": d["icao_code"], "name": d["airline_name"],
                 "total": d["afm_total_fleet"], "active": d["afm_active_fleet"],
                 "country": d["country"], "region": d["region"]}
                for d in top_afm],
    "top_opensky": [{"icao": d["icao_code"], "name": d["airline_name"],
                     "registered": d["opensky_registered_fleet"]}
                    for d in top_osk],
    "unavailable_kpis": [
        "Fleet Growth YoY %", "Fleet CAGR", "Aircraft on Order", "Options",
        "Firm Orders", "Deliveries Next 12 Months", "Deliveries Next 3 Years",
        "Order-to-Fleet Ratio", "Expected Fleet Growth", "Fleet Utilization",
        "Replacement Ratio", "Retired Aircraft", "Aircraft Added",
        "Seats per Aircraft", "New Aircraft Growth", "Retirement Rate",
    ],
    "unavailable_reason": unavail_reason,
}
(OUT / "KPI_SUMMARY.json").write_text(json.dumps(summary, indent=2))
print("KPI summary:", json.dumps({k: v for k, v in summary.items()
      if k not in ("top_afm", "top_opensky")}, indent=1)[:1200])
print("DONE")
