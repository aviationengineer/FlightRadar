"""Google Sheets sink for the AirLabs fleet pipeline.

Writes via the Hatch Google Workspace CLI so auth stays inside the
managed connector — no service-account JSON in Python.

CLI contract (verified against ``hatch_gws_cli sheets ... --help``):
- query/path params go in ``--params <JSON>``
- request bodies go in ``--json <JSON>``
- large frames must be chunked (~100 KB per CLI call) to stay under the
  argv length limit, with a short throttle between chunks.

Reuses the shared LIB ``GoogleSheetsSink`` for plain appends/reads and
adds the worksheet management + formatting the LIB sink lacks (it
hard-codes sheetId 0 for formatting, which is wrong for non-first tabs).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any, Sequence

sys.path.insert(0, os.path.expanduser("~/workspace"))

from LIB.sheets import GoogleSheetsSink as _LibSink  # noqa: E402
from LIB.sheets import SheetsSinkError  # noqa: E402

CLI = "/opt/hatch/bin/hatch_gws_cli"

# Keep each CLI invocation comfortably under MAX_ARG_STRLEN (128 KB).
_CHUNK_BYTES = 100 * 1024
_CHUNK_THROTTLE_SECONDS = 0.5


def _byte_chunks(rows: list[list[Any]], limit: int = _CHUNK_BYTES):
    """Yield row groups whose JSON encoding stays under ``limit`` bytes."""
    chunk: list[list[Any]] = []
    size = 0
    for row in rows:
        row_size = len(json.dumps(row, default=str))
        if chunk and size + row_size > limit:
            yield chunk
            chunk, size = [], 0
        chunk.append(row)
        size += row_size
    if chunk:
        yield chunk


def _col_letter(idx: int) -> str:
    result = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        result = chr(65 + rem) + result
    return result


class AirlabsSheetsSink:
    """Writes AirLabs fleet tables to the Fleet Intelligence sheet."""

    def __init__(self, spreadsheet_id: str | None = None,
                 cli: str = CLI):
        self.spreadsheet_id = spreadsheet_id
        self.cli = cli
        self._lib = _LibSink(spreadsheet_id=spreadsheet_id)

    # ------------------------------------------------------------------
    # low-level CLI
    # ------------------------------------------------------------------
    def _run(self, *args: str, body: dict | None = None,
             params: dict | None = None) -> dict[str, Any]:
        cmd = [self.cli, "sheets", *args]
        if params is not None:
            cmd += ["--params", json.dumps(params)]
        if body is not None:
            cmd += ["--json", json.dumps(body)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as exc:
            raise SheetsSinkError(f"Failed to run {' '.join(cmd[:6])}...: {exc}") from exc
        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            raise SheetsSinkError(
                f"CLI failed ({proc.returncode}): {(proc.stderr or out)[:1000]}"
            )
        if not out:
            return {}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"_raw": out}

    def _require_id(self) -> str:
        if not self.spreadsheet_id:
            raise SheetsSinkError("No spreadsheet_id set.")
        return self.spreadsheet_id

    # ------------------------------------------------------------------
    # worksheets
    # ------------------------------------------------------------------
    def get_sheet_id(self, title: str) -> int | None:
        sid = self._require_id()
        meta = self._run("spreadsheets", "get", params={"spreadsheetId": sid})
        for sh in meta.get("sheets", []):
            props = sh.get("properties", {})
            if props.get("title") == title:
                return props.get("sheetId")
        return None

    def list_tabs(self) -> list[str]:
        sid = self._require_id()
        meta = self._run("spreadsheets", "get", params={"spreadsheetId": sid})
        return [s.get("properties", {}).get("title", "")
                for s in meta.get("sheets", [])]

    def ensure_worksheet(self, title: str) -> int:
        """Create the tab if missing; return its sheetId."""
        sid = self.get_sheet_id(title)
        if sid is not None:
            return sid
        self._run("spreadsheets", "batchUpdate",
                  params={"spreadsheetId": self._require_id()},
                  body={"requests": [{"addSheet": {"properties": {"title": title}}}]})
        new_id = self.get_sheet_id(title)
        if new_id is None:
            raise SheetsSinkError(f"Could not create/find tab {title!r}")
        return new_id

    def format_tab(self, title: str, ncols: int) -> None:
        """Bold header row + light fill, freeze row 1, add a filter."""
        sheet_id = self.ensure_worksheet(title)
        self._run(
            "spreadsheets", "batchUpdate",
            params={"spreadsheetId": self._require_id()},
            body={"requests": [
                {"repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": ncols},
                    "cell": {"userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.9, "green": 0.93, "blue": 0.96}}},
                    "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
                {"updateSheetProperties": {
                    "properties": {"sheetId": sheet_id,
                                   "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount"}},
                {"setBasicFilter": {"filter": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": ncols}}}},
            ]},
        )

    # ------------------------------------------------------------------
    # values
    # ------------------------------------------------------------------
    def read_table(self, tab: str, max_rows: int | None = None) -> list[list[Any]]:
        """Read a tab (header + rows). Empty tab -> []."""
        sid = self._require_id()
        rng = f"{tab}!A1:ZZ{max_rows + 1}" if max_rows else f"{tab}!A1:ZZ"
        res = self._run("spreadsheets", "values", "get",
                        params={"spreadsheetId": sid, "range": rng})
        return res.get("values", [])

    def clear_tab(self, tab: str) -> None:
        self.ensure_worksheet(tab)
        self._run("spreadsheets", "values", "clear",
                  params={"spreadsheetId": self._require_id(),
                          "range": f"{tab}!A:ZZ"})

    def write_table(self, tab: str, headers: Sequence[str],
                    rows: list[list[Any]], replace: bool = True) -> int:
        """Write header + rows to a tab.

        With replace=True the tab is cleared first (full snapshot write).
        Rows are written in ~100 KB chunks to respect the CLI arg limit.
        Returns the number of data rows written.
        """
        self.ensure_worksheet(tab)
        if replace:
            self.clear_tab(tab)
            values: list[list[Any]] = [list(headers)] + [list(r) for r in rows]
            chunks = list(_byte_chunks(values[1:], _CHUNK_BYTES)) if rows else []
            first = [list(headers)] + (chunks[0] if chunks else [])
            self._write_values(tab, first)
            for chunk in chunks[1:]:
                time.sleep(_CHUNK_THROTTLE_SECONDS)
                self._append_values(tab, chunk)
            self.format_tab(tab, len(headers))
            return len(rows)
        # append mode
        self.ensure_header(tab, headers)
        for chunk in _byte_chunks([list(r) for r in rows], _CHUNK_BYTES):
            self._append_values(tab, chunk)
            time.sleep(_CHUNK_THROTTLE_SECONDS)
        return len(rows)

    def ensure_header(self, tab: str, headers: Sequence[str]) -> None:
        """Write + format the header row if the tab is empty."""
        self.ensure_worksheet(tab)
        existing = self.read_table(tab, max_rows=1)
        if not existing:
            self._write_values(tab, [list(headers)])
            self.format_tab(tab, len(headers))

    def append_rows(self, tab: str, rows: list[list[Any]],
                    headers: Sequence[str] | None = None) -> int:
        """Append rows (chunked). Creates/formats the header if needed."""
        if not rows:
            return 0
        if headers is not None:
            self.ensure_header(tab, headers)
        for i, chunk in enumerate(_byte_chunks([list(r) for r in rows], _CHUNK_BYTES)):
            if i:
                time.sleep(_CHUNK_THROTTLE_SECONDS)
            self._append_values(tab, chunk)
        return len(rows)

    # -- raw value calls -------------------------------------------------
    def _write_values(self, tab: str, values: list[list[Any]]) -> None:
        if not values:
            return
        last_col = _col_letter(max(len(r) for r in values) - 1)
        self._run(
            "spreadsheets", "values", "update",
            params={"spreadsheetId": self._require_id(),
                    "range": f"{tab}!A1:{last_col}{len(values)}",
                    "valueInputOption": "USER_ENTERED"},
            body={"values": values},
        )

    def _append_values(self, tab: str, values: list[list[Any]]) -> None:
        if not values:
            return
        self._run(
            "spreadsheets", "values", "append",
            params={"spreadsheetId": self._require_id(),
                    "range": f"{tab}!A:A",
                    "valueInputOption": "USER_ENTERED"},
            body={"values": values},
        )


# Backwards-compatible alias (mirrors the FR24 framework's sink name).
GoogleSheetsSink = AirlabsSheetsSink
