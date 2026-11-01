"""Master Google Sheets sink - shared by all frameworks.

Uses the Hatch Google Workspace CLI so auth stays in the managed
connector. No service-account JSON needed when running inside Muse.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Sequence

CLI = "/opt/hatch/bin/hatch_gws_cli"


class SheetsSinkError(Exception):
    pass


class GoogleSheetsSink:
    """Generic sheet writer for any tabular data."""

    def __init__(
        self,
        spreadsheet_id: str | None = None,
        tab_name: str = "Data",
        headers: Sequence[str] | None = None,
    ):
        self.spreadsheet_id = spreadsheet_id
        self.tab_name = tab_name
        self.headers = list(headers) if headers else []

    def _run(self, *args: str) -> dict[str, Any]:
        cmd = [CLI, "sheets", *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except Exception as exc:
            raise SheetsSinkError(f"Failed to run {' '.join(cmd)}: {exc}") from exc
        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            raise SheetsSinkError(f"CLI failed ({proc.returncode}): {proc.stderr[:1000] or out[:1000]}")
        if not out:
            return {}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"_raw": out}

    def _require_id(self) -> str:
        if not self.spreadsheet_id:
            raise SheetsSinkError("No spreadsheet_id set. Call create_spreadsheet() first.")
        return self.spreadsheet_id

    def create_spreadsheet(self, title: str) -> str:
        res = self._run("spreadsheets", "create", "--json", json.dumps({"properties": {"title": title}}))
        sid = res.get("spreadsheetId") or res.get("spreadsheet_id") or str(res.get("id", ""))
        if not sid:
            raise SheetsSinkError(f"Could not parse spreadsheetId from {res}")
        self.spreadsheet_id = sid
        return sid

    def _col_letter(self, idx: int) -> str:
        result = ""
        idx += 1
        while idx:
            idx, rem = divmod(idx - 1, 26)
            result = chr(65 + rem) + result
        return result

    def ensure_header(self, headers: Sequence[str] | None = None) -> None:
        hdrs = list(headers) if headers else self.headers
        if not hdrs:
            raise SheetsSinkError("No headers provided")
        self.headers = hdrs
        sid = self._require_id()
        last_col = self._col_letter(len(hdrs) - 1)
        existing = self._run(
            "spreadsheets", "values", "get",
            "--params", json.dumps({"spreadsheetId": sid, "range": f"{self.tab_name}!A1:{last_col}1"}),
        )
        if not existing.get("values"):
            self._run(
                "spreadsheets", "values", "update",
                "--params", json.dumps({
                    "spreadsheetId": sid,
                    "range": f"{self.tab_name}!A1:{last_col}1",
                    "valueInputOption": "RAW",
                }),
                "--json", json.dumps({"values": [hdrs]}),
            )
            self._run(
                "spreadsheets", "batchUpdate",
                "--params", json.dumps({"spreadsheetId": sid}),
                "--json", json.dumps({"requests": [
                    {"repeatCell": {
                        "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }},
                    {"updateSheetProperties": {
                        "properties": {"sheetId": 0, "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }},
                ]}),
            )

    def append_rows(self, rows: list[list[Any]], headers: Sequence[str] | None = None) -> int:
        if not rows:
            return 0
        sid = self._require_id()
        self.ensure_header(headers)
        last_col = self._col_letter(len(self.headers) - 1)
        self._run(
            "spreadsheets", "values", "append",
            "--params", json.dumps({
                "spreadsheetId": sid,
                "range": f"{self.tab_name}!A:{last_col}",
                "valueInputOption": "USER_ENTERED",
            }),
            "--json", json.dumps({"values": rows}),
        )
        return len(rows)

    def read_range(self, a1_range: str) -> list[list[Any]]:
        sid = self._require_id()
        res = self._run(
            "spreadsheets", "values", "get",
            "--params", json.dumps({"spreadsheetId": sid, "range": a1_range}),
        )
        return res.get("values", [])
