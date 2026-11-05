"""Configuration for the AirLabs Fleet API pipeline.

Free-tier facts (verified against https://airlabs.co/docs/fleets):
- Base URL: https://airlabs.co/api/v9
- Auth: ``api_key`` query parameter, server-side only.
- Free tier: 1,000 requests/month, 250/minute, 2,500/hour.
- ``limit`` max 500 rows/request, 50 for free keys.
- Errors: minute_limit_exceeded, hour_limit_exceeded, month_limit_exceeded.

The API key is read ONLY from the environment (AIRLABS_API_KEY). There is
no key in this repo, and no code here ever signs up for one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Default destination sheet ("Fleet Intelligence").
DEFAULT_SPREADSHEET_ID = "1cTgndcs_1egjtc8ND5cZvjrQPjHLpZeRIllnQTLBKHo"

#: Tabs owned by this pipeline in the Fleet Intelligence sheet.
TAB_FLEETS = "AIRLABS_Fleets"
TAB_QUALITY = "AIRLABS_Data_Quality"
TAB_LOG = "AIRLABS_Ingestion_Log"
TAB_CATALOG = "Fleet_Catalog"  # shared catalog tab — owned by this pipeline

#: Top 50 airlines by fleet size (IATA codes, approximate order).
#: Used for the weekly refresh rotation. The monthly full pull covers
#: every airline; this list only scopes the cheaper weekly refreshes.
TOP_AIRLINES_IATA: list[str] = [
    "AA", "DL", "UA", "WN", "FR", "U2", "AS", "B6", "NK", "F9",
    "HA", "G4", "6E", "AI", "EK", "QR", "BA", "LH", "AF", "KL",
    "TK", "SU", "CZ", "MU", "CA", "HU", "ZH", "3U", "MF", "EY",
    "SV", "WY", "MS", "ET", "KE", "OZ", "NH", "JL", "QF", "VA",
    "NZ", "AC", "WS", "AM", "LA", "G3", "AD", "AR", "AV", "CM",
]

#: Fields requested from /fleets via ``_fields`` — keeps payloads small.
#: (The endpoint has no airline *name* field; names come from /airlines.)
FLEET_FIELDS = "hex,reg_number,airline_icao,airline_iata,icao,model,manufacturer,age"

#: Fields requested from /airlines for name enrichment.
AIRLINE_FIELDS = "name,iata_code,icao_code"

#: Soft monthly quota cap — well under the 1,000-request free limit.
#: The pipeline refuses to start a new pull once this is reached.
MONTHLY_SOFT_CAP = 900

#: Planning estimate for one monthly full fleet pull, in requests.
#: The global fleet is ~25,000-30,000 airframes; at 50 rows/request
#: (free-key page size) that is ~500-600 requests. The FIRST live run
#: must measure the real number and update this value + the README.
FULL_PULL_REQUEST_ESTIMATE = 600

#: How many top airlines each weekly refresh covers (rotating slice).
WEEKLY_SLICE_SIZE = 10

MISSING_KEY_MESSAGE = (
    "AIRLABS_API_KEY is not set — key missing. "
    "Get a free key at https://airlabs.co (sign up, copy the key from "
    "your account dashboard) and set AIRLABS_API_KEY in the environment "
    "or a local .env file. This tool never signs up for a key on your behalf."
)


@dataclass(frozen=True)
class AirlabsConfig:
    """Holds AirLabs API configuration.

    Attributes:
        api_key: Free API key from airlabs.co (server-side only).
        base_url: Base URL, defaults to https://airlabs.co/api/v9
        page_size: Rows per /fleets request. Max 50 on free keys, 500 paid.
        timeout_seconds: HTTP timeout per request.
        retry_minute_limit: If True, retry once after 65s on
            minute_limit_exceeded; hour/month limits always fail fast.
        retry_delay_seconds: Sleep before that single retry.
        spreadsheet_id: Destination "Fleet Intelligence" sheet.
        cache_dir / state_dir: On-disk cache + quota/rotation state.
        full_cache_ttl_days: How long a full-pull cache stays usable.
        airline_cache_ttl_days: How long a per-airline cache stays usable.
        airline_names_ttl_days: How long the /airlines name map is cached.
        monthly_soft_cap: Refuse new pulls past this many reqs/month.
        weekly_slice_size: Top airlines covered per weekly refresh.
        top_airlines: IATA codes for the weekly refresh rotation.
    """

    api_key: str
    base_url: str = "https://airlabs.co/api/v9"
    page_size: int = 50
    timeout_seconds: int = 30
    retry_minute_limit: bool = True
    retry_delay_seconds: int = 65
    spreadsheet_id: str = DEFAULT_SPREADSHEET_ID
    cache_dir: Path = Path(__file__).resolve().parent / "data" / "cache"
    state_dir: Path = Path(__file__).resolve().parent / "data" / "state"
    full_cache_ttl_days: int = 28
    airline_cache_ttl_days: int = 7
    airline_names_ttl_days: int = 30
    monthly_soft_cap: int = MONTHLY_SOFT_CAP
    weekly_slice_size: int = WEEKLY_SLICE_SIZE
    top_airlines: list[str] = field(default_factory=lambda: list(TOP_AIRLINES_IATA))

    @classmethod
    def from_env(cls) -> "AirlabsConfig":
        key = os.getenv("AIRLABS_API_KEY", "").strip()
        if not key:
            raise ValueError(MISSING_KEY_MESSAGE)
        page_size = int(os.getenv("AIRLABS_PAGE_SIZE", "50"))
        # Free keys are capped at 50 rows/request by the API.
        page_size = max(1, min(page_size, 500))
        return cls(
            api_key=key,
            base_url=os.getenv("AIRLABS_BASE_URL", "https://airlabs.co/api/v9").rstrip("/"),
            page_size=page_size,
            timeout_seconds=int(os.getenv("AIRLABS_TIMEOUT", "30")),
            retry_minute_limit=os.getenv("AIRLABS_RETRY_MINUTE_LIMIT", "true").lower() == "true",
            retry_delay_seconds=int(os.getenv("AIRLABS_RETRY_DELAY", "65")),
            spreadsheet_id=os.getenv(
                "AIRLABS_SHEET_ID", os.getenv("GOOGLE_SHEET_ID", DEFAULT_SPREADSHEET_ID)
            ),
            cache_dir=Path(os.getenv(
                "AIRLABS_CACHE_DIR",
                str(Path(__file__).resolve().parent / "data" / "cache"),
            )),
            state_dir=Path(os.getenv(
                "AIRLABS_STATE_DIR",
                str(Path(__file__).resolve().parent / "data" / "state"),
            )),
            full_cache_ttl_days=int(os.getenv("AIRLABS_FULL_CACHE_TTL_DAYS", "28")),
            airline_cache_ttl_days=int(os.getenv("AIRLABS_AIRLINE_CACHE_TTL_DAYS", "7")),
            airline_names_ttl_days=int(os.getenv("AIRLABS_NAMES_TTL_DAYS", "30")),
            monthly_soft_cap=int(os.getenv("AIRLABS_MONTHLY_SOFT_CAP", str(MONTHLY_SOFT_CAP))),
            weekly_slice_size=int(os.getenv("AIRLABS_WEEKLY_SLICE", str(WEEKLY_SLICE_SIZE))),
        )
