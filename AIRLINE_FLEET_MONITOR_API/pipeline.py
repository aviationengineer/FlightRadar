"""Orchestration: Airline Fleet Monitor export -> transform -> Google Sheets.

Primary flow (weekly): download the bulk airlines export once, keep the
active carriers, run quality checks, and replace the three AFM tabs in the
"Fleet Intelligence" workbook with fresh snapshots. No API key is needed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .afm_client import AirlineFleetMonitorClient
from .config import AFMConfig
from .models import AirlineFleet, DataQualityRow, IngestionLogRow
from .sheets_sink import AFMSheetsSink
from .transforms import (
    export_to_fleets,
    fleets_to_rows,
    quality_summary,
    run_quality_checks,
    total_airframes,
)

TAB_FLEETS = "AFM_Fleets"
TAB_QUALITY = "AFM_Data_Quality"
TAB_LOG = "AFM_Ingestion_Log"
SOURCE_EXPORT = "https://airlinefleetmonitor.com/data/airlines.json"


@dataclass
class IngestionResult:
    fetched: int = 0
    airlines_written: int = 0
    total_airframes: int = 0
    quality: dict[str, int] = field(default_factory=dict)
    spreadsheet_id: str = ""
    source: str = SOURCE_EXPORT
    errors: list[str] = field(default_factory=list)


class FleetMonitorPipeline:
    """High-level pipeline for the weekly AFM fleet snapshot."""

    def __init__(
        self,
        client: AirlineFleetMonitorClient | None = None,
        sink: AFMSheetsSink | None = None,
        config: AFMConfig | None = None,
    ):
        self.config = config or AFMConfig.from_env()
        self.client = client or AirlineFleetMonitorClient(self.config)
        sheet_id = os.getenv("GOOGLE_SHEET_ID") or self.config.spreadsheet_id
        self.sink = sink or AFMSheetsSink(spreadsheet_id=sheet_id)

    # ------------------------------------------------------------------
    # primary run: bulk export
    # ------------------------------------------------------------------
    def run_export(self, write: bool = True) -> IngestionResult:
        """Fetch the bulk export, transform, quality-check, write 3 tabs."""
        result = IngestionResult(spreadsheet_id=self.sink.spreadsheet_id or "")
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            raw = self.client.get_airlines_export()
            result.fetched = len(raw)
            fleets = export_to_fleets(raw, fetched_at=fetched_at)
            checks = run_quality_checks(raw, fleets, fetched_at=fetched_at)
            result.quality = quality_summary(checks)
            result.total_airframes = total_airframes(fleets)
            if write:
                result.airlines_written = self.sink.write_snapshot(
                    TAB_FLEETS, AirlineFleet.sheet_headers(), fleets_to_rows(fleets)
                )
                self.sink.write_snapshot(
                    TAB_QUALITY, DataQualityRow.sheet_headers(),
                    [c.to_sheet_row() for c in checks],
                )
                log = IngestionLogRow(
                    run_at=fetched_at,
                    source=SOURCE_EXPORT,
                    records_fetched=result.fetched,
                    airlines_written=result.airlines_written,
                    total_airframes=result.total_airframes,
                    status="OK" if not result.errors else "PARTIAL",
                    notes=(
                        f"quality PASS={result.quality.get('PASS', 0)} "
                        f"WARN={result.quality.get('WARN', 0)} "
                        f"FAIL={result.quality.get('FAIL', 0)}; "
                        f"snapshot date on site 2026-09-17; "
                        f"idle/stored split is 0 for all records in source (see AFM_Data_Quality)"
                    ),
                )
                self.sink.append_rows(
                    TAB_LOG, IngestionLogRow.sheet_headers(), [log.to_sheet_row()]
                )
            else:
                result.airlines_written = len(fleets)
        except Exception as exc:  # keep pipeline non-throwing; report in result
            result.errors.append(str(exc))
            if write:
                try:
                    log = IngestionLogRow(
                        run_at=fetched_at,
                        source=SOURCE_EXPORT,
                        records_fetched=result.fetched,
                        airlines_written=0,
                        total_airframes=0,
                        status="FAILED",
                        notes=str(exc)[:500],
                    )
                    self.sink.append_rows(
                        TAB_LOG, IngestionLogRow.sheet_headers(), [log.to_sheet_row()]
                    )
                except Exception:
                    pass
        return result

    # ------------------------------------------------------------------
    # spot check: single airline via the per-airline API
    # ------------------------------------------------------------------
    def run_airline(self, slug: str) -> AirlineFleet:
        """Fetch one airline via /api/v1/airlines/{slug} (verification)."""
        fleet = self.client.get_airline(slug)
        if not fleet.fetched_at:
            fleet.fetched_at = datetime.now(timezone.utc).isoformat()
        return fleet
