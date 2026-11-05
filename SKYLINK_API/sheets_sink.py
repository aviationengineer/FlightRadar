"""Google Sheets sink for the Skylink pipeline.

Reuses the shared LIB sink (LIB.sheets.GoogleSheetsSink) for the Hatch
Google Workspace CLI transport — auth stays in the managed connector, no
service-account JSON in Python. This module adds what the LIB sink does
not: per-tab creation, header formatting against the tab's real sheetId
(bold + frozen header row + filter), and chunked appends.

Chunking: the Sheets CLI takes the request body via --json, and large
argument strings hit the OS arg limit. Rows are therefore appended in
chunks whose JSON payload stays under ~100 KB.
"""

from __future__ import annotations

import json
import sys
import os
from typing import Any, Sequence

sys.path.insert(0, os.path.expanduser("~/workspace"))

from LIB.sheets import GoogleSheetsSink as _LibSink, SheetsSinkError  # noqa: E402

#: Max JSON bytes per append chunk (CLI arg-limit safety margin).
MAX_CHUNK_JSON_BYTES = 100_000


class SkylinkSheetsSink(_LibSink):
    """Writes Skylink rows to named tabs of one spreadsheet."""

    def __init__(self, spreadsheet_id: str | None = None):
        super().__init__(spreadsheet_id=spreadsheet_id, tab_name="SKYLINK_Fleets")

    # ------------------------------------------------------------------
    # tab management
    # ------------------------------------------------------------------
    def _sheet_id_for_tab(self, tab_name: str) -> int | None:
        sid = self._require_id()
        meta = self._run("spreadsheets", "get", "--params", json.dumps({"spreadsheetId": sid}))
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == tab_name:
                return int(props.get("sheetId"))
        return None

    def ensure_tab(self, tab_name: str) -> int:
        """Create the tab if missing; return its sheetId."""
        sheet_id = self._sheet_id_for_tab(tab_name)
        if sheet_id is not None:
            return sheet_id
        sid = self._require_id()
        self._run(
            "spreadsheets", "batchUpdate",
            "--params", json.dumps({"spreadsheetId": sid}),
            "--json", json.dumps({"requests": [
                {"addSheet": {"properties": {"title": tab_name}}}
            ]}),
        )
        sheet_id = self._sheet_id_for_tab(tab_name)
        if sheet_id is None:
            raise SheetsSinkError(f"Could not create/find tab {tab_name!r}")
        return sheet_id

    # ------------------------------------------------------------------
    # headers (bold + frozen + filter, against the tab's real sheetId)
    # ------------------------------------------------------------------
    def ensure_header_for_tab(self, tab_name: str, headers: Sequence[str]) -> None:
        sheet_id = self.ensure_tab(tab_name)
        sid = self._require_id()
        last_col = self._col_letter(len(headers) - 1)
        existing = self._run(
            "spreadsheets", "values", "get",
            "--params", json.dumps({
                "spreadsheetId": sid,
                "range": f"{tab_name}!A1:{last_col}1",
            }),
        )
        if existing.get("values"):
            return
        self._run(
            "spreadsheets", "values", "update",
            "--params", json.dumps({
                "spreadsheetId": sid,
                "range": f"{tab_name}!A1:{last_col}1",
                "valueInputOption": "RAW",
            }),
            "--json", json.dumps({"values": [list(headers)]}),
        )
        self._run(
            "spreadsheets", "batchUpdate",
            "--params", json.dumps({"spreadsheetId": sid}),
            "--json", json.dumps({"requests": [
                {"repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }},
                {"updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }},
                {"setBasicFilter": {
                    "filter": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(headers),
                        }
                    }
                }},
            ]}),
        )

    # ------------------------------------------------------------------
    # chunked appends
    # ------------------------------------------------------------------
    @staticmethod
    def chunk_rows(
        rows: list[list[Any]],
        max_json_bytes: int = MAX_CHUNK_JSON_BYTES,
    ) -> list[list[list[Any]]]:
        """Split rows into chunks whose JSON payload stays under the limit."""
        chunks: list[list[list[Any]]] = []
        current: list[list[Any]] = []
        current_bytes = 2  # "[]"
        for row in rows:
            row_bytes = len(json.dumps(row, default=str).encode("utf-8")) + 1
            if current and current_bytes + row_bytes > max_json_bytes:
                chunks.append(current)
                current, current_bytes = [], 2
            current.append(row)
            current_bytes += row_bytes
        if current:
            chunks.append(current)
        return chunks

    def append_rows_to_tab(
        self,
        tab_name: str,
        headers: Sequence[str],
        rows: list[list[Any]],
    ) -> int:
        """Ensure tab + header, then append rows in ~100 KB chunks."""
        if not rows:
            self.ensure_header_for_tab(tab_name, headers)
            return 0
        sid = self._require_id()
        self.ensure_header_for_tab(tab_name, headers)
        last_col = self._col_letter(len(headers) - 1)
        written = 0
        for chunk in self.chunk_rows(rows):
            self._run(
                "spreadsheets", "values", "append",
                "--params", json.dumps({
                    "spreadsheetId": sid,
                    "range": f"{tab_name}!A:{last_col}",
                    "valueInputOption": "USER_ENTERED",
                }),
                "--json", json.dumps({"values": chunk}),
            )
            written += len(chunk)
        return written


# Backwards-compatible alias (FR24 framework names its sink this way).
GoogleSheetsSink = SkylinkSheetsSink
