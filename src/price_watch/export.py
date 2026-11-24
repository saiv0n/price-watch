from __future__ import annotations

import csv
import json
from pathlib import Path


def _columns(rows: list[dict]) -> list[str]:
    cols: dict[str, None] = {}
    for r in rows:
        cols.update(dict.fromkeys(r))
    return list(cols)


def write(rows: list[dict], path: str | Path) -> Path:
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
