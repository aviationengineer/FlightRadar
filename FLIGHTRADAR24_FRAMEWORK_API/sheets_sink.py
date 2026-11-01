"""Google Sheets sink using the Hatch Google Workspace CLI.

This keeps auth inside the managed connector – no service-account JSON
needed in Python. Requires Google Sheets to be connected in Muse.

CLI reference: /opt/hatch/bin/hatch_gws_cli sheets ...
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .models import Flight

CLI = "/opt/hatch/bin/hatch_gws_cli"


class SheetsSinkError(Exception):
    pass


class GoogleSheetsSink:
    """Writes Flight rows to a Google Sheet."""

    def __init__(self, spreadsheet_id: str | None = None, tab_name: str = "Flights"):
        self.spreadsheet_id = spreadsheet_id
        self.tab_name = tab_name

    # ------------------------------------------------------------------
    # low-level CLI
    # ------------------------------------------------------------------
    def _run(self, *args: str) -> dict[str, Any]:
        cmd = [CLI, "sheets", *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except Exception as exc:
            raise SheetsSinkError(f"Failed to run {' '.join(cmd)}: {exc}") from exc

        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            raise SheetsSinkError(
                f"CLI failed ({proc.returncode}): {proc.stderr[:1000] or out[:1000]}"
            )
        if not out:
            return {}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            # Some commands print non-JSON; return raw
            return {"_raw": out}

    def _require_id(self) -> str:
        if not self.spreadsheet_id:
            raise SheetsSinkError(
                "No spreadsheet_id set. Call create_spreadsheet() first or "
                "pass GOOGLE_SHEET_ID."
            )
        return self.spreadsheet_id

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def create_spreadsheet(self, title: str) -> str:
        """Create a new spreadsheet and remember its ID."""
        res = self._run(
            "spreadsheets", "create",
            "--json", json.dumps({"properties": {"title": title}}),
        )
        sid = res.get("spreadsheetId") or res.get("spreadsheet_id") or ""
        if not sid:
            # try nested
            sid = str(res.get("id", ""))
        if not sid:
            raise SheetsSinkError(f"Could not parse spreadsheetId from {res}")
        self.spreadsheet_id = sid
        return sid

    def ensure_header(self) -> None:
        """Write header row if the sheet is empty."""
        sid = self._require_id()
        existing = self._run(
            "spreadsheets", "values", "get",
            "--params", json.dumps({
                "spreadsheetId": sid,
                "range": f"{self.tab_name}!A1:Q1",
            }),
        )
        values = existing.get("values", [])
        if not values:
            self._run(
                "spreadsheets", "values", "update",
                "--params", json.dumps({
                    "spreadsheetId": sid,
                    "range": f"{self.tab_name}!A1:Q1",
                    "valueInputOption": "RAW",
                }),
                "--json", json.dumps({"values": [Flight.sheet_headers()]}),
            )
            # Freeze header + bold it
            self._run(
                "spreadsheets", "batchUpdate",
                "--params", json.dumps({"spreadsheetId": sid}),
                "--json", json.dumps({
                    "requests": [
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": 0,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1,
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "textFormat": {"bold": True}
                                    }
                                },
                                "fields": "userEnteredFormat.textFormat.bold",
                            }
                        },
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": 0,
                                    "gridProperties": {"frozenRowCount": 1}
                                },
                                "fields": "gridProperties.frozenRowCount",
                            }
                        },
                    ]
                }),
            )

    def append_flights(self, flights: list[Flight]) -> int:
        """Append flight rows. Returns number of rows written."""
        if not flights:
            return 0
        sid = self._require_id()
        self.ensure_header()
        rows = [f.to_sheet_row() for f in flights]
        self._run(
            "spreadsheets", "values", "append",
            "--params", json.dumps({
                "spreadsheetId": sid,
                "range": f"{self.tab_name}!A:Q",
                "valueInputOption": "USER_ENTERED",
            }),
            "--json", json.dumps({"values": rows}),
        )
        return len(rows)

    def read_recent(self, max_rows: int = 10) -> list[list[Any]]:
        sid = self._require_id()
        res = self._run(
            "spreadsheets", "values", "get",
            "--params", json.dumps({
                "spreadsheetId": sid,
                "range": f"{self.tab_name}!A1:Q{max_rows + 1}",
            }),
        )
        return res.get("values", [])
