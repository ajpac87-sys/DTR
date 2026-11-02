"""
Loading the fleet list from a spreadsheet saved as CSV.

Nobody should type 50 units in one by one. Save the fleet list from Excel or
Google Sheets as CSV and upload it. Column names are matched loosely ("Unit",
"Unit #", "Truck #" all mean the unit number).

ALL OR NOTHING. The upload is checked first and every problem is listed by
row. Nothing is saved until the whole file is clean, so a fleet list never
goes in half-loaded.
"""
from __future__ import annotations

import csv
import io
import re

from ..i18n import Msg
from .units import build_unit, unit_key

MAX_ROWS = 2000

# Column heading (lowercased, punctuation removed) -> field.
_ALIASES = {
    "unit_number": {"unit", "unit number", "unit no", "unit num", "unit #",
                    "unit id", "truck", "truck number", "truck #",
                    "trailer number", "trailer #", "number", "fleet number",
                    "company number", "asset", "asset number", "asset id"},
    "asset_type": {"type", "unit type", "asset type", "kind", "equipment type",
                   "vehicle type"},
    "vin": {"vin", "vin number", "serial", "serial number", "vin serial"},
    "make": {"make", "manufacturer", "mfr"},
    "model": {"model"},
    "model_year": {"year", "model year", "yr"},
    "plate": {"plate", "license plate", "license", "plate number", "tag",
              "license number"},
    "plate_state": {"state", "plate state", "license state", "tag state"},
    "furnished_by": {"owner", "owned by", "furnished by", "lessor",
                     "owner name"},
    "odometer": {"odometer", "miles", "mileage", "odo"},
    "engine_hours": {"engine hours", "hours", "hrs", "eng hours"},
    "notes": {"notes", "note", "comments", "comment"},
}


def _norm(h: str) -> str:
    h = (h or "").replace("﻿", "").strip().lower()
    h = h.replace("#", " # ")
    h = re.sub(r"[^a-z0-9#]+", " ", h)
    return re.sub(r"\s+", " ", h).strip()


_LOOKUP = {_norm(a): f for f, names in _ALIASES.items() for a in names}


def map_headers(headers: list[str]) -> tuple[dict[int, str], list[str]]:
    """Which column is which field, and the columns we will ignore."""
    mapping: dict[int, str] = {}
    ignored: list[str] = []
    for i, h in enumerate(headers):
        f = _LOOKUP.get(_norm(h))
        if f and f not in mapping.values():
            mapping[i] = f
        elif (h or "").strip():
            ignored.append(h.strip())
    return mapping, ignored


def read_csv(raw: bytes) -> list[list[str]]:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("csv.err.unreadable")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect)
            if any(c.strip() for c in r)]


def check_file(raw: bytes, existing_keys: set[str]) -> dict:
    """
    Check an uploaded fleet list. Saves nothing.

    `existing_keys` are the unit numbers this company already has, so a
    re-upload doesn't create duplicates.
    """
    try:
        rows = read_csv(raw)
    except ValueError as e:
        return {"ok": False, "problems": [Msg(str(e))], "rows": [], "units": []}
    if not rows:
        return {"ok": False, "problems": [Msg("csv.err.empty")], "rows": [],
                "units": []}

    mapping, ignored = map_headers(rows[0])
    problems: list[str] = []
    if "unit_number" not in mapping.values():
        problems.append(Msg("csv.err.no_unit_column"))
    if "asset_type" not in mapping.values():
        problems.append(Msg("csv.err.no_type_column"))
    body = rows[1:]
    if not body:
        problems.append(Msg("csv.err.no_rows"))
    if len(body) > MAX_ROWS:
        problems.append(Msg("csv.err.too_many", n=len(body), limit=MAX_ROWS))
    if problems:
        return {"ok": False, "problems": problems, "rows": [], "units": [],
                "columns": {rows[0][i]: f for i, f in mapping.items()},
                "ignored_columns": ignored}

    results, units = [], []
    seen: dict[str, int] = {}
    for n, row in enumerate(body, start=2):     # row 1 is the headings
        data = {f: (row[i] if i < len(row) else "") for i, f in mapping.items()}
        unit, errors, warnings = build_unit(data)
        key = unit_key(unit.get("unit_number") or "")
        if key and key in existing_keys:
            errors.append(Msg("unit.err.exists", unit=unit["unit_number"]))
        if key and key in seen:
            errors.append(Msg("csv.err.dup_row", unit=unit["unit_number"], row=seen[key]))
        if key:
            seen.setdefault(key, n)
        results.append({"row": n, "unit_number": unit.get("unit_number"),
                        "asset_type": unit.get("asset_type"),
                        "errors": errors, "warnings": warnings})
        units.append(unit)

    bad = sum(1 for r in results if r["errors"])
    return {
        "ok": bad == 0,
        "problems": ([Msg("csv.err.rows_bad", n=bad)]
                     if bad else []),
        "rows": results,
        "units": units if bad == 0 else [],
        "count": len(results),
        "power_units": sum(1 for u in units if u["asset_type"] == "power_unit"),
        "trailers": sum(1 for u in units if u["asset_type"] == "trailer"),
        "columns": {rows[0][i]: f for i, f in mapping.items()},
        "ignored_columns": ignored,
    }
