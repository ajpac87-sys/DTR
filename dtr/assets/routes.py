"""Web routes for trucks and trailers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from .. import changelog
from ..auth import signed_in
from ..db import CompanyData
from ..i18n import Msg, Problem, lang_of, tr
from ..access import EDIT_UNITS, IMPORT_UNITS, Person
from . import csv_import
from .units import ACTIVE, EDITABLE, RETIRED, TYPES, build_unit, unit_key

router = APIRouter(prefix="/api/assets")
MAX_UPLOAD = 2 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _need(p: Person, perm: str) -> None:
    if p.is_operator:
        raise Problem(403, Msg("err.operator_read_only"))
    if not p.may(perm):
        raise Problem(403, Msg("err.role_cannot_edit_units"))


def _stamp(unit: dict, p: Person) -> dict:
    now = _now()
    for f in ("odometer", "engine_hours"):
        if unit.get(f) is not None:
            unit[f + "_at"] = now
            unit[f + "_by"] = p.name
    return unit


class UnitIn(BaseModel):
    asset_type: str | None = None
    unit_number: str | None = None
    vin: str | None = None
    make: str | None = None
    model: str | None = None
    model_year: int | str | None = None
    plate: str | None = None
    plate_state: str | None = None
    owned_by_carrier: bool | None = None
    furnished_by: str | None = None
    odometer: float | str | None = None
    engine_hours: float | str | None = None
    notes: str | None = None


@router.get("")
async def list_units(q: str = "", type: str = "", status: str = ACTIVE,
                     p: Person = Depends(signed_in)):
    cond: dict = {}
    if status in (ACTIVE, RETIRED):
        cond["status"] = status
    if type in TYPES:
        cond["asset_type"] = type
    rows = await CompanyData(p).find("assets", cond,
                                  sort=[("unit_number_key", 1)])
    if q.strip():
        needle = q.strip().upper()
        rows = [r for r in rows if needle in r["unit_number_key"]
                or needle in (r.get("vin") or "")
                or needle in (r.get("plate") or "").upper()]
    return {"units": rows, "types": TYPES}


@router.get("/{asset_id}")
async def get_unit(asset_id: str, p: Person = Depends(signed_in)):
    u = await CompanyData(p).find_one("assets", {"asset_id": asset_id})
    if not u:
        raise Problem(404, Msg("err.no_such_unit"))
    return u


async def _taken(data: CompanyData, key: str, but: str | None = None) -> bool:
    cond: dict = {"unit_number_key": key}
    if but:
        cond["asset_id"] = {"$ne": but}
    return await data.count("assets", cond) > 0


@router.post("", status_code=201)
async def add_unit(body: UnitIn, p: Person = Depends(signed_in),
                   lang: str = Depends(lang_of)):
    _need(p, EDIT_UNITS)
    data = CompanyData(p)
    unit, errors, warnings = build_unit(body.model_dump())
    if not errors and await _taken(data, unit["unit_number_key"]):
        errors.append(Msg("unit.err.exists", unit=unit["unit_number"]))
    if errors:
        raise Problem(400, {"errors": errors, "warnings": warnings})
    unit.update(asset_id=uuid.uuid4().hex, status=ACTIVE, retired_at=None,
                created_at=_now(), created_by=p.user_id)
    unit = await data.insert("assets", _stamp(unit, p))
    await changelog.write(data, p, "unit.created", "asset", unit["asset_id"],
                       after=unit)
    return {"unit": unit, "warnings": tr(warnings, lang)}


@router.patch("/{asset_id}")
async def edit_unit(asset_id: str, body: UnitIn,
                    p: Person = Depends(signed_in),
                    lang: str = Depends(lang_of)):
    _need(p, EDIT_UNITS)
    data = CompanyData(p)
    old = await data.find_one("assets", {"asset_id": asset_id})
    if not old:
        raise Problem(404, Msg("err.no_such_unit"))
    sent = body.model_dump(exclude_unset=True)
    merged = {f: old.get(f) for f in EDITABLE}
    merged.update({k: v for k, v in sent.items() if k in EDITABLE})
    unit, errors, warnings = build_unit(merged)
    if not errors and await _taken(data, unit["unit_number_key"], asset_id):
        errors.append(Msg("unit.err.exists", unit=unit["unit_number"]))
    if errors:
        raise Problem(400, {"errors": errors, "warnings": warnings})
    changes = {k: v for k, v in unit.items() if old.get(k) != v}
    for f in ("odometer", "engine_hours"):
        if f in changes and changes[f] is not None:
            changes[f + "_at"], changes[f + "_by"] = _now(), p.name
    if changes:
        await data.update("assets", {"asset_id": asset_id}, changes)
        await changelog.write(data, p, "unit.edited", "asset", asset_id,
                           before={k: old.get(k) for k in changes},
                           after=changes)
    return {"unit": {**old, **changes}, "warnings": tr(warnings, lang)}


class RetireIn(BaseModel):
    reason: str


@router.post("/{asset_id}/retire")
async def retire_unit(asset_id: str, body: RetireIn,
                      p: Person = Depends(signed_in)):
    """
    Take a unit out of the fleet (sold, scrapped, returned). It is kept, not
    deleted: its records must stay 6 months after it leaves (396.3(c), per
    the brief).
    """
    _need(p, EDIT_UNITS)
    if not body.reason.strip():
        raise Problem(400, Msg("err.retire_reason_required"))
    data = CompanyData(p)
    old = await data.find_one("assets", {"asset_id": asset_id})
    if not old:
        raise Problem(404, Msg("err.no_such_unit"))
    if old["status"] == RETIRED:
        raise Problem(400, Msg("err.already_retired"))
    changes = {"status": RETIRED, "retired_at": _now(),
               "retired_reason": body.reason.strip()}
    await data.update("assets", {"asset_id": asset_id}, changes)
    await changelog.write(data, p, "unit.retired", "asset", asset_id,
                       before={"status": old["status"]}, after=changes)
    return {"unit": {**old, **changes}}


@router.post("/import")
async def import_units(file: UploadFile = File(...), commit: bool = False,
                       p: Person = Depends(signed_in),
                       lang: str = Depends(lang_of)):
    """
    Check a fleet-list CSV (commit=false), then load it (commit=true).
    Loads only when every row is clean.
    """
    _need(p, IMPORT_UNITS)
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise Problem(400, Msg("csv.err.too_big"))
    data = CompanyData(p)
    existing = {u["unit_number_key"] for u in await data.find("assets")}
    result = csv_import.check_file(raw, existing)
    units = result.pop("units")
    if not commit or not result["ok"]:
        return tr({**result, "saved": 0}, lang)
    now = _now()
    docs = []
    for u in units:
        u.update(asset_id=uuid.uuid4().hex, status=ACTIVE, retired_at=None,
                 created_at=now, created_by=p.user_id,
                 imported_from=file.filename)
        docs.append(_stamp(u, p))
    await data.insert_many("assets", docs)
    await changelog.write(data, p, "units.imported", "asset", "import",
                       after={"file": file.filename, "count": len(docs),
                              "asset_ids": [d["asset_id"] for d in docs]})
    return tr({**result, "saved": len(docs)}, lang)
