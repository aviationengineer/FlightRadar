"""Orchestration: FR24 → transform → Google Sheets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import FR24Config
from .fr24_client import FlightRadar24Client
from .models import Flight
from .sheets_sink import GoogleSheetsSink
from .transforms import dedupe_by_fr24_id


@dataclass
class IngestionResult:
    fetched: int = 0
    deduped: int = 0
    written: int = 0
    spreadsheet_id: str = ""
    errors: list[str] = field(default_factory=list)


class FlightIngestionPipeline:
    """High-level pipeline for live flight ingestion."""

    def __init__(
        self,
        client: FlightRadar24Client | None = None,
        sink: GoogleSheetsSink | None = None,
        config: FR24Config | None = None,
    ):
        self.config = config or FR24Config.from_env()
        self.client = client or FlightRadar24Client(self.config)
        sheet_id = os.getenv("GOOGLE_SHEET_ID") or None
        tab = os.getenv("GOOGLE_SHEET_TAB", "Flights")
        self.sink = sink or GoogleSheetsSink(spreadsheet_id=sheet_id, tab_name=tab)

    def ensure_sink(self, title_prefix: str = "FR24 Flights") -> str:
        """Create a spreadsheet if none is configured. Returns spreadsheet ID."""
        if not self.sink.spreadsheet_id:
            title = f"{title_prefix} – {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
            sid = self.sink.create_spreadsheet(title)
            return sid
        return self.sink.spreadsheet_id

    def run_live(
        self,
        bounds: str,
        full: bool = False,
        limit: int | None = None,
        create_sheet_if_needed: bool = True,
    ) -> IngestionResult:
        """Fetch live flights in bounds and append to Google Sheet.

        Args:
            bounds: "N,S,W,E" – e.g. "51.5,51.0,-0.5,0.2" for London
            full: use full (richer, more credits) vs light endpoint
            limit: cap number of flights written
            create_sheet_if_needed: auto-create spreadsheet if not set
        """
        result = IngestionResult()
        try:
            if create_sheet_if_needed:
                result.spreadsheet_id = self.ensure_sink()
            else:
                result.spreadsheet_id = self.sink.spreadsheet_id or ""

            if full:
                flights = self.client.get_live_positions_full(bounds, limit=limit)
            else:
                flights = self.client.get_live_positions_light(bounds, limit=limit)

            result.fetched = len(flights)
            flights = dedupe_by_fr24_id(flights)
            result.deduped = len(flights)

            # Stamp missing timestamps with now (UTC)
            now_iso = datetime.now(timezone.utc).isoformat()
            for f in flights:
                if not f.timestamp_utc:
                    f.timestamp_utc = now_iso

            result.written = self.sink.append_flights(flights)
        except Exception as exc:  # keep pipeline non-throwing; report in result
            result.errors.append(str(exc))
        return result

    def run_for_airports(
        self,
        airport_bounds: dict[str, str],
        full: bool = False,
        limit_per_airport: int | None = 50,
    ) -> dict[str, IngestionResult]:
        """Run live ingestion for multiple named bounding boxes.

        Example:
            {"Heathrow": "51.6,51.4,-0.6,-0.3", "JFK": "40.8,40.5,-73.9,-73.6"}
        """
        results: dict[str, IngestionResult] = {}
        self.ensure_sink()
        for name, bounds in airport_bounds.items():
            # Write to same sheet; flights already carry origin/dest
            res = self.run_live(
                bounds=bounds,
                full=full,
                limit=limit_per_airport,
                create_sheet_if_needed=False,
            )
            results[name] = res
        return results
