"""Web routes for trucks and trailers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import audit
from ..auth import current_principal
from ..db import TenantDB, db
from ..tenancy import EDIT_UNITS, IMPORT_UNITS, Principal
from . import csv_import
from .units import ACTIVE, EDITABLE, RETIRED, TYPES, build_unit, unit_key

router = APIRouter(prefix="/api/assets")
MAX_UPLOAD = 2 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _need(p: Principal, perm: str) -> None:
    if p.is_operator:
        raise HTTPException(403, "Apex can view units but not change them "
                                 "from here.")
    if not p.may(perm):
        raise HTTPException(403, "Your role can't change units.")


def _stamp(unit: dict, p: Principal) -> dict:
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
                     p: Principal = Depends(current_principal)):
    cond: dict = {}
    if status in (ACTIVE, RETIRED):
        cond["status"] = status
    if type in TYPES:
        cond["asset_type"] = type
    rows = await TenantDB(p).find("assets", cond,
                                  sort=[("unit_number_key", 1)])
    if q.strip():
        needle = q.strip().upper()
        rows = [r for r in rows if needle in r["unit_number_key"]
                or needle in (r.get("vin") or "")
                or needle in (r.get("plate") or "").upper()]
    return {"units": rows, "types": TYPES}


@router.get("/{asset_id}")
async def get_unit(asset_id: str, p: Principal = Depends(current_principal)):
    u = await TenantDB(p).find_one("assets", {"asset_id": asset_id})
    if not u:
        raise HTTPException(404, "No such unit.")
    return u


async def _taken(tdb: TenantDB, key: str, but: str | None = None) -> bool:
    cond: dict = {"unit_number_key": key}
    if but:
        cond["asset_id"] = {"$ne": but}
    return await tdb.count("assets", cond) > 0


@router.post("", status_code=201)
async def add_unit(body: UnitIn, p: Principal = Depends(current_principal)):
    _need(p, EDIT_UNITS)
    tdb = TenantDB(p)
    unit, errors, warnings = build_unit(body.model_dump())
    if not errors and await _taken(tdb, unit["unit_number_key"]):
        errors.append(f"Unit {unit['unit_number']} is already in DTR.")
    if errors:
        raise HTTPException(400, {"errors": errors, "warnings": warnings})
    unit.update(asset_id=uuid.uuid4().hex, status=ACTIVE, retired_at=None,
                created_at=_now(), created_by=p.user_id)
    unit = await tdb.insert("assets", _stamp(unit, p))
    await audit.record(tdb, p, "unit.created", "asset", unit["asset_id"],
                       after=unit)
    return {"unit": unit, "warnings": warnings}


@router.patch("/{asset_id}")
async def edit_unit(asset_id: str, body: UnitIn,
                    p: Principal = Depends(current_principal)):
    _need(p, EDIT_UNITS)
    tdb = TenantDB(p)
    old = await tdb.find_one("assets", {"asset_id": asset_id})
    if not old:
        raise HTTPException(404, "No such unit.")
    sent = body.model_dump(exclude_unset=True)
    merged = {f: old.get(f) for f in EDITABLE}
    merged.update({k: v for k, v in sent.items() if k in EDITABLE})
    unit, errors, warnings = build_unit(merged)
    if not errors and await _taken(tdb, unit["unit_number_key"], asset_id):
        errors.append(f"Unit {unit['unit_number']} is already in DTR.")
    if errors:
        raise HTTPException(400, {"errors": errors, "warnings": warnings})
    changes = {k: v for k, v in unit.items() if old.get(k) != v}
    for f in ("odometer", "engine_hours"):
        if f in changes and changes[f] is not None:
            changes[f + "_at"], changes[f + "_by"] = _now(), p.name
    if changes:
        await tdb.update("assets", {"asset_id": asset_id}, changes)
        await audit.record(tdb, p, "unit.edited", "asset", asset_id,
                           before={k: old.get(k) for k in changes},
                           after=changes)
    return {"unit": {**old, **changes}, "warnings": warnings}


class RetireIn(BaseModel):
    reason: str


@router.post("/{asset_id}/retire")
async def retire_unit(asset_id: str, body: RetireIn,
                      p: Principal = Depends(current_principal)):
    """
    Take a unit out of the fleet (sold, scrapped, returned). It is kept, not
    deleted: its records must stay 6 months after it leaves (396.3(c), per
    the brief).
    """
    _need(p, EDIT_UNITS)
    if not body.reason.strip():
        raise HTTPException(400, "Say why the unit is leaving the fleet.")
    tdb = TenantDB(p)
    old = await tdb.find_one("assets", {"asset_id": asset_id})
    if not old:
        raise HTTPException(404, "No such unit.")
    if old["status"] == RETIRED:
        raise HTTPException(400, "This unit is already out of the fleet.")
    changes = {"status": RETIRED, "retired_at": _now(),
               "retired_reason": body.reason.strip()}
    await tdb.update("assets", {"asset_id": asset_id}, changes)
    await audit.record(tdb, p, "unit.retired", "asset", asset_id,
                       before={"status": old["status"]}, after=changes)
    return {"unit": {**old, **changes}}


@router.post("/import")
async def import_units(file: UploadFile = File(...), commit: bool = False,
                       p: Principal = Depends(current_principal)):
    """
    Check a fleet-list CSV (commit=false), then load it (commit=true).
    Loads only when every row is clean.
    """
    _need(p, IMPORT_UNITS)
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, "The file is over 2 MB. A fleet list "
                                 "should be far smaller; is it the right file?")
    tdb = TenantDB(p)
    existing = {u["unit_number_key"] for u in await tdb.find("assets")}
    result = csv_import.check_file(raw, existing)
    units = result.pop("units")
    if not commit or not result["ok"]:
        return {**result, "saved": 0}
    now = _now()
    docs = []
    for u in units:
        u.update(asset_id=uuid.uuid4().hex, status=ACTIVE, retired_at=None,
                 created_at=now, created_by=p.user_id,
                 imported_from=file.filename)
        docs.append(_stamp(u, p))
    await tdb.insert_many("assets", docs)
    await audit.record(tdb, p, "units.imported", "asset", "import",
                       after={"file": file.filename, "count": len(docs),
                              "asset_ids": [d["asset_id"] for d in docs]})
    return {**result, "saved": len(docs)}
