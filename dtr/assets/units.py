"""
Trucks and trailers: the rules for a unit record.

A power unit and a trailer are SEPARATE units, always. Hooking them together
will be a dated pairing record (not built yet), never a merged unit.

The identification fields follow 49 CFR 396.3(b)(1) as the project brief
states it (see regulatory.py; not yet re-checked against eCFR).

No database or web code here, so the rules can be tested directly.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

POWER_UNIT = "power_unit"
TRAILER = "trailer"
TYPES = {POWER_UNIT: "Power unit", TRAILER: "Trailer"}

ACTIVE = "active"
RETIRED = "retired"   # sold, scrapped, returned. Kept, never deleted (396.3(c)).

# Words people actually put in a "type" column, mapped to the two kinds.
_TYPE_WORDS = {
    POWER_UNIT: {"power unit", "power_unit", "powerunit", "pu", "truck",
                 "tractor", "straight truck", "box truck", "bobtail",
                 "power"},
    TRAILER: {"trailer", "van", "dry van", "reefer", "flatbed", "tanker",
              "chassis", "dolly", "converter dolly", "lowboy", "step deck",
              "trl", "tr"},
}

_VIN_CHARS = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_VIN_VALUES = {**{str(d): d for d in range(10)},
               **dict(zip("ABCDEFGH", range(1, 9))),
               **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9,
               **dict(zip("STUVWXYZ", range(2, 10)))}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def parse_type(text: str | None) -> str | None:
    t = (text or "").strip().lower()
    for kind, words in _TYPE_WORDS.items():
        if t in words:
            return kind
    return None


def unit_key(unit_number: str) -> str:
    """How unit numbers are compared: ' 101 ' and '101' are the same unit."""
    return re.sub(r"\s+", " ", (unit_number or "").strip()).upper()


def vin_check_digit_ok(vin: str) -> bool:
    total = sum(_VIN_VALUES[c] * w for c, w in zip(vin, _VIN_WEIGHTS))
    r = total % 11
    return vin[8] == ("X" if r == 10 else str(r))


def check_vin(vin: str | None) -> tuple[str | None, list[str], list[str]]:
    """
    Clean up a VIN and say what is wrong with it.

    Returns (cleaned VIN or None, errors, warnings). A blank VIN is allowed
    (some old trailers have none on record yet) and comes back as a warning.
    A wrong check digit is a WARNING, not an error: VINs from before 1981 and
    some non-North-American VINs do not use one, so refusing would block a
    real unit. A mechanic should look at the plate.
    """
    v = re.sub(r"[\s-]", "", (vin or "")).upper()
    if not v:
        return None, [], ["No VIN entered."]
    if len(v) != 17:
        if len(v) < 17:
            return v, [], [f"VIN is {len(v)} characters, not 17. Fine for "
                           "a pre-1981 unit; otherwise check the plate."]
        return None, [f"VIN is {len(v)} characters; a VIN has 17."], []
    if not _VIN_CHARS.match(v):
        return None, ["VIN has a character a VIN never uses (I, O and Q "
                      "are never used)."], []
    if not vin_check_digit_ok(v):
        return v, [], ["VIN check digit doesn't add up. Check it against "
                       "the plate on the unit."]
    return v, [], []


def check_year(year) -> tuple[int | None, list[str]]:
    if year in (None, ""):
        return None, []
    try:
        y = int(str(year).strip())
    except ValueError:
        return None, [f"Year '{year}' is not a number."]
    latest = datetime.now(timezone.utc).year + 1
    if not 1950 <= y <= latest:
        return None, [f"Year {y} is outside 1950 to {latest}."]
    return y, []


def check_reading(value, what: str) -> tuple[float | None, list[str]]:
    if value in (None, ""):
        return None, []
    try:
        n = float(str(value).replace(",", "").strip())
    except ValueError:
        return None, [f"{what} '{value}' is not a number."]
    if n < 0:
        return None, [f"{what} can't be negative."]
    return n, []


def build_unit(data: dict) -> tuple[dict, list[str], list[str]]:
    """
    Turn entered fields into a clean unit record.

    Returns (record, errors, warnings). If there are errors the record must
    not be saved.
    """
    errors: list[str] = []
    warnings: list[str] = []
    out: dict = {}

    kind = data.get("asset_type")
    kind = kind if kind in TYPES else parse_type(kind)
    if not kind:
        errors.append("Say whether it's a power unit or a trailer.")
    out["asset_type"] = kind

    unit = re.sub(r"\s+", " ", str(data.get("unit_number") or "").strip())
    if not unit:
        errors.append("Unit number is required.")
    elif len(unit) > 30:
        errors.append("Unit number is longer than 30 characters.")
    out["unit_number"] = unit
    out["unit_number_key"] = unit_key(unit)

    vin, e, w = check_vin(data.get("vin"))
    errors += e
    warnings += w
    out["vin"] = vin

    year, e = check_year(data.get("model_year"))
    errors += e
    out["model_year"] = year

    for f in ("make", "model", "plate", "plate_state", "notes"):
        v = str(data.get(f) or "").strip()
        out[f] = v or None
    if out["plate_state"]:
        out["plate_state"] = out["plate_state"].upper()[:3]

    furnished = str(data.get("furnished_by") or "").strip()
    owned = data.get("owned_by_carrier")
    if owned is None:
        owned = not furnished
    owned = bool(owned)
    if not owned and not furnished:
        errors.append("This unit isn't owned by the company, so enter who "
                      "furnishes it (owner's name).")
    out["owned_by_carrier"] = owned
    out["furnished_by"] = None if owned else furnished

    odo, e = check_reading(data.get("odometer"), "Odometer")
    errors += e
    hrs, e = check_reading(data.get("engine_hours"), "Engine hours")
    errors += e
    out["odometer"] = odo
    out["engine_hours"] = hrs
    if kind == TRAILER and hrs is not None:
        warnings.append("Engine hours entered on a trailer. Fine for a "
                        "reefer unit; otherwise check.")

    if not out["make"]:
        warnings.append("No make entered.")
    if year is None:
        warnings.append("No year entered.")
    return out, errors, warnings


# Fields a person may change after the unit is created.
EDITABLE = ("asset_type", "unit_number", "vin", "make", "model", "model_year",
            "plate", "plate_state", "owned_by_carrier", "furnished_by",
            "odometer", "engine_hours", "notes")
