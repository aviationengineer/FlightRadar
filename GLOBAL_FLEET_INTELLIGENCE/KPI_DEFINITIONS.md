# KPI Definitions — Global Airline Fleet Intelligence

Every KPI lists its formula, its source, and whether it is available.
**N/A** means no source is connected — the value is never estimated.

## Available KPIs

| KPI | Formula | Source | Value (2026-11-05) |
|---|---|---|---|
| Total Fleet | Σ AFM `total` | AFM | 25,226 |
| Active Fleet | Σ AFM `active` | AFM | 25,226 (idle/stored are 0 in source) |
| Registered Fleet | Σ OpenSky `total_fleet` | OpenSky | 41,752 (known-operator subset) |
| Airlines | Count of AFM airlines | AFM | 860 |
| Operators | Count of OpenSky operators | OpenSky | 1,750 |
| Average Fleet Age | Mean AirLabs `age` (age > 0) | AirLabs | 10.8 yrs (337 of 649) |
| Aircraft <5 / 5–10 / 10–15 / 15–20 / >20 Years | Count of AirLabs aircraft in each band | AirLabs | 124 / 42 / 72 / 54 / 45 |
| Widebody % | Widebody / (AirLabs + Skylink aircraft) | AirLabs + Skylink | 24.3% |
| Narrowbody % | Narrowbody / (AirLabs + Skylink aircraft) | AirLabs + Skylink | 42.5% |
| Regional % | Regional / (AirLabs + Skylink aircraft) | AirLabs + Skylink | 10.1% |
| Airbus % | Airbus / (AirLabs + Skylink aircraft) | AirLabs + Skylink | derived from typecode |
| Boeing % | Boeing / (AirLabs + Skylink aircraft) | AirLabs + Skylink | derived from typecode |
| Airbus Dependency | Airbus fleet / total fleet (per airline) | Skylink snapshot | per airline |
| Boeing Dependency | Boeing fleet / total fleet (per airline) | Skylink snapshot | per airline |
| Aircraft >15 Years % | (>15 yrs) / (aircraft with known age) | AirLabs | 29.4% (99 of 337) |
| Aircraft per Airline | Total fleet / airlines | AFM | 29.3 |
| Fleet by Region | Σ AFM total by region | AFM | North America 7,559; Asia-Pacific 7,050; Europe 6,963; Middle East 1,454; Latin America 829; Africa 729; Unknown 642 |

## Unavailable KPIs (N/A — Data unavailable)

| KPI | Formula | Missing source |
|---|---|---|
| Fleet Growth YoY % | (Fleet_t − Fleet_{t−1}) / Fleet_{t−1} | Fleet history (year-over-year snapshots) |
| Fleet CAGR | (Fleet_t / Fleet_0)^(1/n) − 1 | Fleet history |
| Aircraft on Order | Σ firm + option orders | Order book |
| Options / Firm Orders | Σ by order_status | Order book |
| Deliveries Next 12 Months / Next 3 Years | Σ orders by delivery date | Order book with delivery dates |
| Order-to-Fleet Ratio | Aircraft on Order / Current Fleet | Order book |
| Expected Fleet Growth | (Current + Firm − Retirements − Current) / Current | Order book + retirement forecast |
| Fleet Utilization | Block hours / available hours | Block hours / cycles |
| Replacement Ratio | New deliveries / retirements | Fleet history (flows) |
| Retired Aircraft / Aircraft Added | Σ by year | Fleet history (flows) |
| Seats per Aircraft | Σ seats / aircraft | Seat capacity per type |
| New Aircraft Growth / Retirement Rate | Flows / fleet | Fleet history (flows) |

## Age-flag thresholds (documented, configurable in the sidebar)

- **GREEN** (healthy / modern): average fleet age ≤ 10.0 years (default).
- **AMBER** (moderate aging pressure): average fleet age ≤ 15.0 years.
- **RED** (high aging / replacement pressure): average fleet age > 15.0 years.

These thresholds are documented defaults, not industry standards — the
sidebar sliders let the user change them, and the dashboard shows the values
in use. No threshold was invented silently.
