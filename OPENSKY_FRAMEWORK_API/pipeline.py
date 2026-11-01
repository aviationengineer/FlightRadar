"""Orchestration: OpenSky → Google Sheets."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/workspace"))
from LIB.sheets import GoogleSheetsSink
from LIB.logging_utils import get_logger

from .config import OpenSkyConfig
from .models import OpenSkyState
from .opensky_client import OpenSkyClient

log = get_logger("opensky-pipeline")


@dataclass
class IngestionResult:
    fetched: int = 0
    written: int = 0
    time: int = 0
    spreadsheet_id: str = ""
    errors: list[str] = field(default_factory=list)


class OpenSkyIngestionPipeline:
    def __init__(
        self,
        client: OpenSkyClient | None = None,
        sink: GoogleSheetsSink | None = None,
        config: OpenSkyConfig | None = None,
    ):
        self.config = config or OpenSkyConfig.from_env()
        self.client = client or OpenSkyClient(self.config)
        sheet_id = os.getenv("GOOGLE_SHEET_ID") or None
        tab = os.getenv("GOOGLE_SHEET_TAB", "OpenSkyStates")
        self.sink = sink or GoogleSheetsSink(
            spreadsheet_id=sheet_id,
            tab_name=tab,
            headers=OpenSkyState.sheet_headers(),
        )

    def ensure_sink(self, title_prefix: str = "OpenSky States") -> str:
        if not self.sink.spreadsheet_id:
            title = f"{title_prefix} – {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
            return self.sink.create_spreadsheet(title)
        return self.sink.spreadsheet_id

    def run_states(
        self,
        lamin: float | None = None,
        lomin: float | None = None,
        lamax: float | None = None,
        lomax: float | None = None,
        create_sheet_if_needed: bool = True,
    ) -> IngestionResult:
        result = IngestionResult()
        try:
            if create_sheet_if_needed:
                result.spreadsheet_id = self.ensure_sink()
            else:
                result.spreadsheet_id = self.sink.spreadsheet_id or ""

            t, states = self.client.get_states(lamin=lamin, lomin=lomin, lamax=lamax, lomax=lomax)
            result.time = t
            result.fetched = len(states)
            rows = [s.to_sheet_row() for s in states]
            result.written = self.sink.append_rows(rows, headers=OpenSkyState.sheet_headers())
            log.info("Fetched %d states, wrote %d", result.fetched, result.written)
        except Exception as exc:
            log.exception("Pipeline failed")
            result.errors.append(str(exc))
        return result
