"""Orchestration: Skylink ADS-B snapshot → transforms → Google Sheets.

Weekly snapshot design (quota-budgeted):
1. One ADS-B request per target airline per page (paginated, capped).
2. Normalise + dedupe by icao24 → one row per airframe actually flying.
3. Registration lookups ONLY for aircraft whose operator is unresolved
   from the ADS-B record, capped at config.max_registration_lookups/run.
4. Write SKYLINK_Fleets (one row per observed aircraft), plus a
   per-airline summary appended to SKYLINK_Ingestion_Log's notes field
   and the quality rows to SKYLINK_Data_Quality.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/workspace"))

from LIB.logging_utils import get_logger  # noqa: E402

from .config import SkylinkConfig  # noqa: E402
from .models import (  # noqa: E402
    AircraftObservation,
    DataQualityRow,
    IngestionLogRow,
)
from .sheets_sink import SkylinkSheetsSink  # noqa: E402
from .skylink_client import SkylinkClient  # noqa: E402
from .transforms import (  # noqa: E402
    dedupe_by_icao24,
    normalize_observations,
    run_quality_checks,
    summarize_by_airline,
)

log = get_logger("skylink-pipeline")

#: Output spreadsheet — "Fleet Intelligence" (shared with other sources;
#: this pipeline writes ONLY its SKYLINK_* tabs, never Fleet_Catalog).
DEFAULT_SPREADSHEET_ID = "1cTgndcs_1egjtc8ND5cZvjrQPjHLpZeRIllnQTLBKHo"
FLEETS_TAB = "SKYLINK_Fleets"
QUALITY_TAB = "SKYLINK_Data_Quality"
LOG_TAB = "SKYLINK_Ingestion_Log"


@dataclass
class IngestionResult:
    fetched: int = 0
    deduped: int = 0
    written: int = 0
    adsb_requests: int = 0
    registration_lookups: int = 0
    operators_resolved: int = 0
    quality_rows: list[DataQualityRow] = field(default_factory=list)
    airline_summary: list[dict] = field(default_factory=list)
    spreadsheet_id: str = ""
    errors: list[str] = field(default_factory=list)


class SkylinkIngestionPipeline:
    """High-level pipeline for the weekly Skylink ADS-B snapshot."""

    def __init__(
        self,
        client: SkylinkClient | None = None,
        sink: SkylinkSheetsSink | None = None,
        config: SkylinkConfig | None = None,
    ):
        self.config = config or SkylinkConfig.from_env()
        self.client = client or SkylinkClient(self.config)
        sheet_id = os.getenv("GOOGLE_SHEET_ID") or DEFAULT_SPREADSHEET_ID
        self.sink = sink or SkylinkSheetsSink(spreadsheet_id=sheet_id)

    # ------------------------------------------------------------------
    # enrichment
    # ------------------------------------------------------------------
    def enrich_unresolved(
        self, observations: list[AircraftObservation]
    ) -> tuple[list[AircraftObservation], int]:
        """Resolve operators via registration lookup — sparingly.

        Only aircraft with no airline/operator from ADS-B get a lookup,
        up to config.max_registration_lookups per run. Returns the
        observations and the count of newly resolved operators.
        """
        unresolved = [o for o in observations if not o.operator_resolved and o.registration]
        budget = min(len(unresolved), self.config.max_registration_lookups)
        resolved = 0
        for obs in unresolved[:budget]:
            try:
                detail = self.client.get_aircraft_by_registration(obs.registration)
            except Exception as exc:  # one bad lookup must not kill the run
                log.warning("Registration lookup failed for %s: %s", obs.registration, exc)
                continue
            if detail.operator:
                obs.operator = detail.operator
                if not obs.airline_name:
                    obs.airline_name = detail.operator
                resolved += 1
            if detail.model and not obs.model:
                obs.model = detail.model
            if detail.manufacturer and not obs.manufacturer:
                obs.manufacturer = detail.manufacturer
            if detail.aircraft_type and not obs.aircraft_type:
                obs.aircraft_type = detail.aircraft_type
        if len(unresolved) > budget:
            log.info(
                "Registration lookup budget exhausted: %d unresolved aircraft "
                "left without lookup (cap %d/run)",
                len(unresolved) - budget, self.config.max_registration_lookups,
            )
        return observations, resolved

    # ------------------------------------------------------------------
    # main run
    # ------------------------------------------------------------------
    def run_weekly_snapshot(
        self,
        airlines: list[str] | tuple[str, ...] | None = None,
        limit_per_airline: int | None = None,
    ) -> IngestionResult:
        """Fetch the weekly ADS-B snapshot and write it to Sheets."""
        result = IngestionResult(spreadsheet_id=self.sink.spreadsheet_id or "")
        run_at = datetime.now(timezone.utc).isoformat()
        targets = list(airlines) if airlines else list(self.config.target_airlines)
        try:
            all_obs: list[AircraftObservation] = []
            for airline in targets:
                obs = self.client.get_adsb_aircraft(
                    airline=airline, limit=limit_per_airline
                )
                log.info("ADS-B: %s → %d aircraft", airline, len(obs))
                all_obs.extend(obs)
            result.fetched = len(all_obs)
            result.adsb_requests = self.client.adsb_requests

            all_obs = normalize_observations(all_obs)
            all_obs = dedupe_by_icao24(all_obs)
            result.deduped = len(all_obs)

            all_obs, resolved = self.enrich_unresolved(all_obs)
            result.operators_resolved = resolved
            result.registration_lookups = self.client.registration_lookups

            result.airline_summary = summarize_by_airline(all_obs)
            result.quality_rows = run_quality_checks(all_obs, observed_at=run_at)

            # SKYLINK_Fleets — one row per observed aircraft.
            result.written = self.sink.append_rows_to_tab(
                FLEETS_TAB,
                AircraftObservation.sheet_headers(),
                [o.to_sheet_row() for o in all_obs],
            )
            # SKYLINK_Data_Quality
            self.sink.append_rows_to_tab(
                QUALITY_TAB,
                DataQualityRow.sheet_headers(),
                [r.to_sheet_row() for r in result.quality_rows],
            )
            # SKYLINK_Ingestion_Log (per-airline summary in notes)
            summary_text = "; ".join(
                f"{s['airline_name']} ({s['airline_icao']}): "
                f"{s['aircraft_observed']} airborne [{s['aircraft_types']}]"
                for s in result.airline_summary
            )
            log_row = IngestionLogRow(
                run_at=run_at,
                airlines_targeted=len(targets),
                adsb_requests=result.adsb_requests,
                registration_lookups=result.registration_lookups,
                aircraft_fetched=result.fetched,
                aircraft_written=result.written,
                operators_resolved=resolved,
                status="OK",
                notes=summary_text[:4000],
            )
            self.sink.append_rows_to_tab(
                LOG_TAB,
                IngestionLogRow.sheet_headers(),
                [log_row.to_sheet_row()],
            )
            log.info(
                "Snapshot OK: fetched=%d deduped=%d written=%d "
                "adsb_requests=%d reg_lookups=%d",
                result.fetched, result.deduped, result.written,
                result.adsb_requests, result.registration_lookups,
            )
        except Exception as exc:  # keep pipeline non-throwing; report in result
            log.exception("Pipeline failed")
            result.errors.append(str(exc))
            try:
                self.sink.append_rows_to_tab(
                    LOG_TAB,
                    IngestionLogRow.sheet_headers(),
                    [IngestionLogRow(
                        run_at=run_at,
                        airlines_targeted=len(targets),
                        adsb_requests=self.client.adsb_requests,
                        registration_lookups=self.client.registration_lookups,
                        aircraft_fetched=result.fetched,
                        aircraft_written=0,
                        status="FAILED",
                        notes=str(exc)[:4000],
                    ).to_sheet_row()],
                )
            except Exception:
                pass
        return result
