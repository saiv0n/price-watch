from __future__ import annotations

import csv
import json
import os
from pathlib import Path


def _columns(rows: list[dict]) -> list[str]:
    cols: dict[str, None] = {}
    for r in rows:
        cols.update(dict.fromkeys(r))
    return list(cols)


def write(rows: list[dict], path: str | Path) -> Path | str:
    if str(path).startswith("sheets:"):
        return write_sheet(rows, str(path))
    path = Path(path)
    cols = _columns(rows)
    match path.suffix.lower():
        case ".csv":
            # utf-8-sig so Excel opens non-ascii text correctly
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
        case ".json":
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        case ".xlsx":
            from openpyxl import Workbook
            from openpyxl.utils import get_column_letter

            wb = Workbook()
            ws = wb.active
            ws.title = "items"
            ws.append(cols)
            for r in rows:
                ws.append([r.get(c) for c in cols])
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for i, c in enumerate(cols, 1):
                width = max([len(str(c))] + [len(str(r.get(c) or "")) for r in rows[:200]])
                ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)
            wb.save(path)
        case _:
            raise ValueError(f"unsupported export format: {path.suffix} (use .csv, .xlsx or .json)")
    return path


def write_sheet(rows: list[dict], target: str) -> str:
    """Replace a worksheet with the rows. target is sheets:<spreadsheet id>[/<worksheet>]."""
    try:
        import gspread
    except ImportError as e:
        raise SystemExit("Google Sheets output needs: pip install 'price-watch[sheets]'") from e

    sheet_id, _, tab = target.removeprefix("sheets:").partition("/")
    creds = os.environ.get("GOOGLE_SERVICE_ACCOUNT")
    gc = gspread.service_account(filename=creds) if creds else gspread.service_account()
    book = gc.open_by_key(sheet_id)
    try:
        ws = book.worksheet(tab) if tab else book.sheet1
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(tab, rows=len(rows) + 1, cols=max(len(_columns(rows)), 1))
    cols = _columns(rows)
    values = [cols] + [["" if r.get(c) is None else r.get(c) for c in cols] for r in rows]
    ws.clear()
    ws.update(values, "A1")
    ws.freeze(rows=1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"
