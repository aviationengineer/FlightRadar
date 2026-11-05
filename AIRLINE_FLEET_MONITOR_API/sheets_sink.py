"""Google Sheets sink for the Airline Fleet Monitor pipeline.

Built on the shared LIB sink (LIB/sheets.py) for the low-level Hatch CLI
calls, with AFM-specific behaviour on top:
- creates the tab if missing (addSheet via batchUpdate) and resolves the
  real sheetId (LIB hardcodes sheetId 0, which is wrong for added tabs),
- snapshot semantics: clear + chunked update, so a weekly re-run replaces
  the previous snapshot instead of appending duplicates,
- headers bold + frozen row 1 + auto-filter, like the sibling frameworks,
- chunked writes (~90 KB of JSON per values.update call) with a 0.5 s
  throttle between chunks — the Hatch CLI arg limit breaks on large
  single writes (lesson from the World Bank / Gmail frameworks).

Tabs owned by this pipeline in the "Fleet Intelligence" workbook:
AFM_Fleets, AFM_Data_Quality, AFM_Ingestion_Log. No other tab is touched.
"""

from __future__ import annotations

import json
import time
from typing import Any, Sequence

import sys
import os

sys.path.insert(0, os.path.expanduser("~/workspace"))

from LIB.sheets import GoogleSheetsSink as _LibSink, SheetsSinkError  # noqa: E402

MAX_CHUNK_BYTES = 90_000
THROTTLE_SECONDS = 0.5


class AFMSheetsSink:
    """Writes AFM snapshots to the Fleet Intelligence workbook."""

    def __init__(self, spreadsheet_id: str | None = None):
        self.lib = _LibSink(spreadsheet_id=spreadsheet_id)
        self.spreadsheet_id = spreadsheet_id

    # ------------------------------------------------------------------
    # low-level (delegated to LIB)
    # ------------------------------------------------------------------
    def _run(self, *args: str) -> dict[str, Any]:
        return self.lib._run(*args)

    def _require_id(self) -> str:
        if not self.spreadsheet_id:
            raise SheetsSinkError("No spreadsheet_id set (GOOGLE_SHEET_ID).")
        return self.spreadsheet_id

    @staticmethod
    def _col_letter(idx: int) -> str:
        result = ""
        idx += 1
        while idx:
            idx, rem = divmod(idx - 1, 26)
            result = chr(65 + rem) + result
        return result

    # ------------------------------------------------------------------
    # tab management
    # ------------------------------------------------------------------
    def get_sheet_id(self, tab_name: str) -> int | None:
        sid = self._require_id()
        meta = self._run("spreadsheets", "get",
                         "--params", json.dumps({"spreadsheetId": sid}))
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == tab_name:
                return props.get("sheetId")
        return None

    def ensure_tab(self, tab_name: str) -> int:
        """Create the tab if missing; return its sheetId."""
        sheet_id = self.get_sheet_id(tab_name)
        if sheet_id is not None:
            return sheet_id
        sid = self._require_id()
        res = self._run(
            "spreadsheets", "batchUpdate",
            "--params", json.dumps({"spreadsheetId": sid}),
            "--json", json.dumps({"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}),
        )
        replies = res.get("replies", [])
        for reply in replies:
            props = (reply.get("addSheet") or {}).get("properties") or {}
            if props.get("title") == tab_name and props.get("sheetId") is not None:
                return props["sheetId"]
        sheet_id = self.get_sheet_id(tab_name)
        if sheet_id is None:
            raise SheetsSinkError(f"Could not create or find tab {tab_name!r}")
        return sheet_id

    # ------------------------------------------------------------------
    # snapshot writes
    # ------------------------------------------------------------------
    def write_snapshot(
        self,
        tab_name: str,
        headers: Sequence[str],
        rows: list[list[Any]],
    ) -> int:
        """Replace a tab's contents with headers + rows (snapshot semantics).

        Clears the tab, writes the header row, then writes data rows in
        ~90 KB chunks via values.update (USER_ENTERED). Applies bold header,
        frozen row 1 and an auto-filter. Returns rows written.
        """
        sid = self._require_id()
        sheet_id = self.ensure_tab(tab_name)
        headers = list(headers)
        last_col = self._col_letter(len(headers) - 1)

        # Clear previous snapshot (generous range; clear is a no-op past the edge).
        self._run(
            "spreadsheets", "values", "clear",
            "--params", json.dumps({"spreadsheetId": sid, "range": f"{tab_name}!A1:{last_col}10000"}),
            "--json", json.dumps({}),
        )
        # Header row.
        self._run(
            "spreadsheets", "values", "update",
            "--params", json.dumps({
                "spreadsheetId": sid,
                "range": f"{tab_name}!A1:{last_col}1",
                "valueInputOption": "RAW",
            }),
            "--json", json.dumps({"values": [headers]}),
        )
        # Format: bold header, freeze row 1, auto-filter over header+data.
        end_row = max(1, len(rows) + 1)
        self._run(
            "spreadsheets", "batchUpdate",
            "--params", json.dumps({"spreadsheetId": sid}),
            "--json", json.dumps({"requests": [
                {"repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }},
                {"updateSheetProperties": {
                    "properties": {"sheetId": sheet_id,
                                   "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }},
                {"setBasicFilter": {
                    "filter": {"range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0, "endRowIndex": end_row,
                        "startColumnIndex": 0, "endColumnIndex": len(headers),
                    }}
                }},
            ]}),
        )
        # Data rows in size-limited chunks.
        written = 0
        chunk: list[list[Any]] = []
        chunk_bytes = 0
        start_row = 2  # 1-based, after header

        def _flush(c: list[list[Any]], first_row: int) -> int:
            if not c:
                return first_row
            last_row = first_row + len(c) - 1
            self._run(
                "spreadsheets", "values", "update",
                "--params", json.dumps({
                    "spreadsheetId": sid,
                    "range": f"{tab_name}!A{first_row}:{last_col}{last_row}",
                    "valueInputOption": "USER_ENTERED",
                }),
                "--json", json.dumps({"values": c}),
            )
            time.sleep(THROTTLE_SECONDS)
            return last_row + 1

        for row in rows:
            row_bytes = len(json.dumps(row, default=str).encode("utf-8"))
            if chunk and chunk_bytes + row_bytes > MAX_CHUNK_BYTES:
                start_row = _flush(chunk, start_row)
                written += len(chunk)
                chunk, chunk_bytes = [], 0
            chunk.append(row)
            chunk_bytes += row_bytes
        if chunk:
            _flush(chunk, start_row)
            written += len(chunk)
        return written

    def append_rows(
        self,
        tab_name: str,
        headers: Sequence[str],
        rows: list[list[Any]],
    ) -> int:
        """Append rows to a tab (used for the append-only ingestion log).

        Ensures the tab + header exist (with formatting), then appends in
        ~90 KB chunks with a 0.5 s throttle.
        """
        if not rows:
            return 0
        sid = self._require_id()
        sheet_id = self.ensure_tab(tab_name)
        headers = list(headers)
        last_col = self._col_letter(len(headers) - 1)
        existing = self._run(
            "spreadsheets", "values", "get",
            "--params", json.dumps({"spreadsheetId": sid, "range": f"{tab_name}!A1:{last_col}1"}),
        )
        if not existing.get("values"):
            self._run(
                "spreadsheets", "values", "update",
                "--params", json.dumps({
                    "spreadsheetId": sid,
                    "range": f"{tab_name}!A1:{last_col}1",
                    "valueInputOption": "RAW",
                }),
                "--json", json.dumps({"values": [headers]}),
            )
            self._run(
                "spreadsheets", "batchUpdate",
                "--params", json.dumps({"spreadsheetId": sid}),
                "--json", json.dumps({"requests": [
                    {"repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }},
                    {"updateSheetProperties": {
                        "properties": {"sheetId": sheet_id,
                                       "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }},
                ]}),
            )
        written = 0
        chunk: list[list[Any]] = []
        chunk_bytes = 0
        for row in rows:
            row_bytes = len(json.dumps(row, default=str).encode("utf-8"))
            if chunk and chunk_bytes + row_bytes > MAX_CHUNK_BYTES:
                self._append_chunk(sid, tab_name, last_col, chunk)
                written += len(chunk)
                chunk, chunk_bytes = [], 0
            chunk.append(row)
            chunk_bytes += row_bytes
        if chunk:
            self._append_chunk(sid, tab_name, last_col, chunk)
            written += len(chunk)
        return written

    def _append_chunk(self, sid: str, tab_name: str, last_col: str,
                      chunk: list[list[Any]]) -> None:
        self._run(
            "spreadsheets", "values", "append",
            "--params", json.dumps({
                "spreadsheetId": sid,
                "range": f"{tab_name}!A:{last_col}",
                "valueInputOption": "USER_ENTERED",
            }),
            "--json", json.dumps({"values": chunk}),
        )
        time.sleep(THROTTLE_SECONDS)

    def read_range(self, a1_range: str) -> list[list[Any]]:
        sid = self._require_id()
        res = self._run(
            "spreadsheets", "values", "get",
            "--params", json.dumps({"spreadsheetId": sid, "range": a1_range}),
        )
        return res.get("values", [])
