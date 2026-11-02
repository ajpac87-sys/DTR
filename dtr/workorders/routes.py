"""Web routes for work orders. The rules live in rules.py."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import changelog
from ..auth import signed_in
from ..db import CompanyData, db
from ..i18n import Msg, Problem, lang_of, text, tr
from ..access import Person, Role
from . import rules as R

router = APIRouter(prefix="/api/workorders")

MAX_PHOTO = 3 * 1024 * 1024
MAX_PHOTOS_PER_JOB = 30
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _deny(ok: bool, key: str = "err.not_allowed") -> None:
    if not ok:
        raise Problem(403, Msg(key))


def _writer(p: Person) -> None:
    if p.is_operator:
        raise Problem(403, Msg("err.operator_read_only"))


def _out(wo: dict) -> dict:
    return {**wo, "totals": R.totals(wo)}


async def _load(data: CompanyData, wid: str) -> dict:
    wo = await data.find_one("work_orders", {"work_order_id": wid})
    if not wo:
        raise Problem(404, Msg("wo.err.not_found"))
    return wo


def _stamp(p: Person) -> dict:
    return {"line_id": uuid.uuid4().hex, "at": _now(), "by": p.user_id,
            "by_name": p.name}


async def _save(data: CompanyData, p: Person, wo: dict, action: str, *,
                changes: dict | None = None, push: dict | None = None,
                before: dict | None = None, after: dict | None = None,
                expect_status: str | tuple | None = None) -> dict:
    """
    Write one change to a job and log it. With `expect_status`, the change
    only applies if the job is still in that status, so two people tapping
    at once can't both win.
    """
    cond = {"work_order_id": wo["work_order_id"]}
    if expect_status:
        st = (expect_status,) if isinstance(expect_status, str) \
            else tuple(expect_status)
        cond["status"] = {"$in": list(st)}
    changes = {**(changes or {}), "updated_at": _now()}
    if not await data.update("work_orders", cond, changes, push):
        raise Problem(409, Msg("wo.err.changed_meanwhile"))
    await changelog.write(data, p, action, "work_order", wo["work_order_id"],
                       before=before, after=after or changes)
    return _out(await _load(data, wo["work_order_id"]))


# --- Reading ------------------------------------------------------------------

@router.get("/meta")
async def meta(p: Person = Depends(signed_in)):
    """Choices for the forms, and who can be assigned."""
    techs = []
    if p.org_id:
        rows = await db().users.find(
            {"org_id": p.org_id, "active": True,
             "role": {"$in": [Role.MECHANIC.value, Role.SHOP_MANAGER.value]}},
            {"_id": 0, "user_id": 1, "name": 1, "role": 1}
        ).sort("name", 1).to_list(None)
        techs = rows
    return {"statuses": R.STATUSES, "priorities": R.PRIORITIES,
            "categories": R.CATEGORIES, "sources": R.SOURCES, "techs": techs,
            "may": {"create": R.may_create(p), "work": R.may_work(p),
                    "lead": R.may_lead(p), "note": R.may_note(p)}}


@router.get("")
async def list_jobs(view: str = "active", mine: bool = False,
                    asset_id: str = "",
                    p: Person = Depends(signed_in)):
    cond: dict = {}
    if view == "active":
        cond["status"] = {"$in": list(R.ACTIVE)}
    elif view in R.STATUSES:
        cond["status"] = view
    if mine:
        cond["$or"] = [{"assigned.user_id": p.user_id},
                       {"labor.user_id": p.user_id}]
    if asset_id:
        cond["asset_id"] = asset_id
    rows = await CompanyData(p).find("work_orders", cond)
    rows.sort(key=R.sort_key if view == "active"
              else (lambda w: -w.get("number", 0)))
    keep = ("work_order_id", "number", "asset_id", "unit_number",
            "asset_type", "status", "priority", "category", "complaint",
            "assigned", "created_at", "org_id", "source")
    return {"work_orders": [{**{k: w.get(k) for k in keep},
                             "totals": R.totals(w)} for w in rows]}


@router.get("/{wid}")
async def get_job(wid: str, p: Person = Depends(signed_in)):
    return _out(await _load(CompanyData(p), wid))


# --- Creating and editing ----------------------------------------------------

class JobIn(BaseModel):
    asset_id: str | None = None
    complaint: str | None = None
    cause: str | None = None
    correction: str | None = None
    priority: str | None = None
    category: str | None = None
    source: str | None = None
    source_ref: str | None = None
    odometer: float | str | None = None
    engine_hours: float | str | None = None


@router.post("", status_code=201)
async def create_job(body: JobIn, p: Person = Depends(signed_in)):
    _writer(p)
    _deny(R.may_create(p))
    data = CompanyData(p)
    sent = body.model_dump(exclude_unset=True)
    sent.setdefault("priority", "normal")
    sent.setdefault("category", "other")
    sent.setdefault("source", "manual")
    fields, errors = R.check_fields(sent)
    unit = None
    if body.asset_id:
        unit = await data.find_one("assets", {"asset_id": body.asset_id})
    if not unit:
        errors.append(Msg("wo.err.need_unit"))
    elif unit.get("status") != "active":
        errors.append(Msg("wo.err.unit_retired"))
    if not fields.get("complaint"):
        errors.append(Msg("wo.err.need_complaint"))
    if errors:
        raise Problem(400, {"errors": errors})
    number = await data.next_number("work_order")
    wo = {
        "work_order_id": uuid.uuid4().hex, "number": number,
        "asset_id": unit["asset_id"], "unit_number": unit["unit_number"],
        "asset_type": unit["asset_type"],
        "complaint": None, "cause": None, "correction": None,
        "source_ref": None, "odometer": None, "engine_hours": None,
        **fields,
        "status": R.OPEN, "assigned": [], "labor": [], "parts": [],
        "vendor": [], "notes": [], "photos": [], "amendments": [],
        "history": [{"at": _now(), "by": p.user_id, "by_name": p.name,
                     "from": None, "to": R.OPEN}],
        "signoff": None, "closed": None, "cancelled": None,
        "created_at": _now(), "created_by": p.user_id,
        "created_name": p.name, "updated_at": _now(),
    }
    wo = await data.insert("work_orders", wo)
    await changelog.write(data, p, "wo.created", "work_order",
                       wo["work_order_id"],
                       after={k: wo[k] for k in ("number", "unit_number",
                                                 "complaint", "priority",
                                                 "category", "source")})
    return _out(wo)


@router.patch("/{wid}")
async def edit_job(wid: str, body: JobIn,
                   p: Person = Depends(signed_in)):
    """Edit a job that hasn't been signed off. Signed jobs use /amend."""
    _writer(p)
    data = CompanyData(p)
    wo = await _load(data, wid)
    _deny(R.may_work(p) or (R.may_create(p) and wo["created_by"] == p.user_id))
    if wo["status"] not in R.ACTIVE:
        raise Problem(400, Msg("wo.err.signed_use_amend"))
    sent = body.model_dump(exclude_unset=True)
    sent.pop("asset_id", None)       # a job never moves to another unit
    fields, errors = R.check_fields(sent)
    if "complaint" in fields and not fields["complaint"]:
        errors.append(Msg("wo.err.need_complaint"))
    if errors:
        raise Problem(400, {"errors": errors})
    changes = {k: v for k, v in fields.items() if wo.get(k) != v}
    if not changes:
        return _out(wo)
    return await _save(data, p, wo, "wo.edited", changes=changes,
                       before={k: wo.get(k) for k in changes}, after=changes,
                       expect_status=R.ACTIVE)


class StatusIn(BaseModel):
    status: str


@router.post("/{wid}/status")
async def move(wid: str, body: StatusIn,
               p: Person = Depends(signed_in)):
    _writer(p)
    _deny(R.may_work(p))
    data = CompanyData(p)
    wo = await _load(data, wid)
    if body.status not in R.MOVES.get(wo["status"], set()):
        raise Problem(400, Msg("wo.err.bad_move"))
    step = {"at": _now(), "by": p.user_id, "by_name": p.name,
            "from": wo["status"], "to": body.status}
    changes = {"status": body.status}
    if body.status == R.IN_PROGRESS and not wo.get("started_at"):
        changes["started_at"] = _now()
    return await _save(data, p, wo, "wo.status", changes=changes,
                       push={"history": step},
                       before={"status": wo["status"]},
                       after={"status": body.status},
                       expect_status=wo["status"])


class AssignIn(BaseModel):
    user_ids: list[str]


@router.post("/{wid}/assign")
async def assign(wid: str, body: AssignIn,
                 p: Person = Depends(signed_in)):
    _writer(p)
    _deny(R.may_lead(p))
    data = CompanyData(p)
    wo = await _load(data, wid)
    if wo["status"] not in R.ACTIVE:
        raise Problem(400, Msg("wo.err.not_open"))
    people = await db().users.find(
        {"org_id": p.org_id, "user_id": {"$in": body.user_ids[:20]},
         "active": True,
         "role": {"$in": [Role.MECHANIC.value, Role.SHOP_MANAGER.value]}},
        {"_id": 0, "user_id": 1, "name": 1}).to_list(None)
    if len(people) != len(set(body.user_ids)):
        raise Problem(400, Msg("wo.err.bad_tech"))
    return await _save(data, p, wo, "wo.assigned",
                       changes={"assigned": people},
                       before={"assigned": wo["assigned"]},
                       after={"assigned": people}, expect_status=R.ACTIVE)


# --- Labor, parts, outside work ------------------------------------------

def _amend_reason(p: Person, wo: dict, reason: str | None) -> dict:
    """
    Adding a line to a signed job is an amendment: it needs a reason and the
    right person, and the line is marked as added afterwards.
    """
    if wo["status"] == R.CANCELLED:
        raise Problem(400, Msg("wo.err.cancelled"))
    if wo["status"] in R.SIGNED:
        _deny(R.may_amend(p, wo), "wo.err.cannot_amend")
        if not (reason or "").strip():
            raise Problem(400, Msg("wo.err.need_reason"))
        return {"amended": True, "reason": reason.strip()}
    return {}


class LaborIn(BaseModel):
    user_id: str | None = None
    hours: float | str | None = None
    date: str | None = None
    note: str | None = None
    reason: str | None = None


@router.post("/{wid}/labor")
async def add_labor(wid: str, body: LaborIn,
                    p: Person = Depends(signed_in)):
    """Hours on the job. A tech logs their own; a shop lead may log anyone's."""
    _writer(p)
    _deny(R.may_work(p))
    data = CompanyData(p)
    wo = await _load(data, wid)
    extra = _amend_reason(p, wo, body.reason)
    who = {"user_id": p.user_id, "name": p.name}
    if body.user_id and body.user_id != p.user_id:
        _deny(R.may_lead(p), "wo.err.own_labor_only")
        u = await db().users.find_one({"org_id": p.org_id,
                                       "user_id": body.user_id},
                                      {"_id": 0, "user_id": 1, "name": 1})
        if not u:
            raise Problem(400, Msg("wo.err.bad_tech"))
        who = u
    line, errors = R.check_labor(body.model_dump())
    if errors:
        raise Problem(400, {"errors": errors})
    line = {**_stamp(p), **who, **line, **extra}
    return await _save(data, p, wo, "wo.labor", push={"labor": line},
                       after={"labor": line}, expect_status=wo["status"])


class PartIn(BaseModel):
    part_number: str | None = None
    description: str | None = None
    qty: float | str | None = None
    unit_cost: float | str | None = None
    reason: str | None = None


@router.post("/{wid}/parts")
async def add_part(wid: str, body: PartIn,
                   p: Person = Depends(signed_in)):
    """
    A part used on the job. Typed in for now; the parts inventory step will
    pull these from stock and take them off the shelf count.
    """
    _writer(p)
    _deny(R.may_work(p))
    data = CompanyData(p)
    wo = await _load(data, wid)
    extra = _amend_reason(p, wo, body.reason)
    line, errors = R.check_part(body.model_dump())
    if errors:
        raise Problem(400, {"errors": errors})
    line = {**_stamp(p), **line, **extra}
    return await _save(data, p, wo, "wo.part", push={"parts": line},
                       after={"part": line}, expect_status=wo["status"])


class VendorIn(BaseModel):
    vendor: str | None = None
    invoice_number: str | None = None
    description: str | None = None
    amount: float | str | None = None
    reason: str | None = None


@router.post("/{wid}/vendor")
async def add_vendor(wid: str, body: VendorIn,
                     p: Person = Depends(signed_in)):
    """Work sent out: a tire shop, a machine shop, a dealer."""
    _writer(p)
    _deny(R.may_work(p))
    data = CompanyData(p)
    wo = await _load(data, wid)
    extra = _amend_reason(p, wo, body.reason)
    line, errors = R.check_vendor(body.model_dump())
    if errors:
        raise Problem(400, {"errors": errors})
    line = {**_stamp(p), **line, **extra}
    return await _save(data, p, wo, "wo.vendor", push={"vendor": line},
                       after={"vendor": line}, expect_status=wo["status"])


class VoidIn(BaseModel):
    kind: str
    line_id: str
    reason: str


@router.post("/{wid}/void")
async def void_line(wid: str, body: VoidIn,
                    p: Person = Depends(signed_in)):
    """
    Cross out a labor, part or outside-work line entered by mistake. It stays
    on the job, marked void, with who, when and why. Never deleted.
    """
    _writer(p)
    _deny(R.may_work(p))
    if body.kind not in ("labor", "parts", "vendor"):
        raise Problem(400, Msg("err.not_allowed"))
    if not body.reason.strip():
        raise Problem(400, Msg("wo.err.need_reason"))
    data = CompanyData(p)
    wo = await _load(data, wid)
    if wo["status"] == R.CANCELLED:
        raise Problem(400, Msg("wo.err.cancelled"))
    if wo["status"] in R.SIGNED:
        _deny(R.may_amend(p, wo), "wo.err.cannot_amend")
    lines = wo.get(body.kind, [])
    idx = next((i for i, l in enumerate(lines)
                if l["line_id"] == body.line_id), None)
    if idx is None or lines[idx].get("voided"):
        raise Problem(404, Msg("wo.err.no_line"))
    line = lines[idx]
    # A tech may cross out only their own lines; a shop lead, anyone's.
    if not R.may_lead(p) and line["by"] != p.user_id:
        _deny(False, "wo.err.own_lines_only")
    mark = {f"{body.kind}.{idx}.voided": True,
            f"{body.kind}.{idx}.void_reason": body.reason.strip(),
            f"{body.kind}.{idx}.voided_by": p.name,
            f"{body.kind}.{idx}.voided_at": _now()}
    cond_status = wo["status"]
    return await _save(data, p, wo, "wo.void", changes=mark,
                       before={body.kind: line},
                       after={"voided": body.line_id,
                              "reason": body.reason.strip()},
                       expect_status=cond_status)


# --- Notes and photos ----------------------------------------------------------

class NoteIn(BaseModel):
    text: str


@router.post("/{wid}/notes")
async def add_note(wid: str, body: NoteIn,
                   p: Person = Depends(signed_in)):
    _writer(p)
    _deny(R.may_note(p))
    t = R.clean_text(body.text)
    if not t:
        raise Problem(400, Msg("err.required", field=Msg("field.note")))
    data = CompanyData(p)
    wo = await _load(data, wid)
    note = {**_stamp(p), "text": t}
    return await _save(data, p, wo, "wo.note", push={"notes": note},
                       after={"note": t})


@router.post("/{wid}/photos")
async def add_photo(wid: str, file: UploadFile = File(...),
                    caption: str = Form(""),
                    p: Person = Depends(signed_in)):
    _writer(p)
    _deny(R.may_note(p))
    data = CompanyData(p)
    wo = await _load(data, wid)
    if len(wo.get("photos", [])) >= MAX_PHOTOS_PER_JOB:
        raise Problem(400, Msg("wo.err.too_many_photos",
                               max=MAX_PHOTOS_PER_JOB))
    if (file.content_type or "") not in PHOTO_TYPES:
        raise Problem(400, Msg("wo.err.photo_type"))
    raw = await file.read(MAX_PHOTO + 1)
    if len(raw) > MAX_PHOTO:
        raise Problem(400, Msg("wo.err.photo_big"))
    meta = {**_stamp(p), "photo_id": uuid.uuid4().hex,
            "caption": R.clean_text(caption), "size": len(raw),
            "content_type": file.content_type}
    await data.insert("wo_photos", {"photo_id": meta["photo_id"],
                                   "work_order_id": wid,
                                   "content_type": file.content_type,
                                   "data": raw, "at": meta["at"],
                                   "by": p.user_id})
    return await _save(data, p, wo, "wo.photo", push={"photos": meta},
                       after={"photo": meta["photo_id"],
                              "caption": meta["caption"]})


@router.get("/{wid}/photos/{photo_id}")
async def get_photo(wid: str, photo_id: str,
                    p: Person = Depends(signed_in)):
    ph = await CompanyData(p).find_one("wo_photos", {"photo_id": photo_id,
                                                  "work_order_id": wid})
    if not ph:
        raise Problem(404, Msg("wo.err.not_found"))
    return Response(bytes(ph["data"]), media_type=ph["content_type"],
                    headers={"Cache-Control": "private, max-age=86400"})


# --- Sign-off, close, cancel, amend ------------------------------------------

class SignIn(BaseModel):
    typed_name: str = ""


@router.post("/{wid}/complete")
async def sign_off(wid: str, body: SignIn,
                   p: Person = Depends(signed_in),
                   lang: str = Depends(lang_of)):
    """
    The tech signs the job complete by typing their own name. The statement
    they agreed to is saved word for word, in the language they read it in.
    """
    _writer(p)
    data = CompanyData(p)
    wo = await _load(data, wid)
    errors = R.check_signoff(p, wo, body.typed_name)
    if errors:
        raise Problem(400, {"errors": errors})
    signoff = {"user_id": p.user_id, "name": p.name, "role": p.role.value,
               "typed_name": body.typed_name.strip(), "at": _now(),
               "statement": text("wo.signoff.statement", lang),
               "statement_lang": lang}
    step = {"at": signoff["at"], "by": p.user_id, "by_name": p.name,
            "from": wo["status"], "to": R.COMPLETE}
    out = await _save(data, p, wo, "wo.signed",
                      changes={"status": R.COMPLETE, "signoff": signoff,
                               "completed_at": signoff["at"]},
                      push={"history": step}, after={"signoff": signoff},
                      expect_status=wo["status"])
    out["warnings"] = tr(R.warnings_at_signoff(wo), lang)
    return out


@router.post("/{wid}/close")
async def close(wid: str, p: Person = Depends(signed_in)):
    """A shop lead has reviewed the signed job. Nothing more to do on it."""
    _writer(p)
    _deny(R.may_lead(p))
    data = CompanyData(p)
    wo = await _load(data, wid)
    if wo["status"] != R.COMPLETE:
        raise Problem(400, Msg("wo.err.close_needs_complete"))
    closed = {"user_id": p.user_id, "name": p.name, "at": _now()}
    step = {"at": closed["at"], "by": p.user_id, "by_name": p.name,
            "from": R.COMPLETE, "to": R.CLOSED}
    return await _save(data, p, wo, "wo.closed",
                       changes={"status": R.CLOSED, "closed": closed},
                       push={"history": step}, after={"closed": closed},
                       expect_status=R.COMPLETE)


class ReasonIn(BaseModel):
    reason: str = ""


@router.post("/{wid}/cancel")
async def cancel(wid: str, body: ReasonIn,
                 p: Person = Depends(signed_in)):
    """For a job that shouldn't exist (a duplicate, raised on the wrong unit)."""
    _writer(p)
    _deny(R.may_lead(p))
    if not body.reason.strip():
        raise Problem(400, Msg("wo.err.need_reason"))
    data = CompanyData(p)
    wo = await _load(data, wid)
    if wo["status"] not in R.ACTIVE:
        raise Problem(400, Msg("wo.err.not_open"))
    c = {"user_id": p.user_id, "name": p.name, "at": _now(),
         "reason": body.reason.strip()}
    step = {"at": c["at"], "by": p.user_id, "by_name": p.name,
            "from": wo["status"], "to": R.CANCELLED,
            "reason": c["reason"]}
    return await _save(data, p, wo, "wo.cancelled",
                       changes={"status": R.CANCELLED, "cancelled": c},
                       push={"history": step}, after={"cancelled": c},
                       expect_status=R.ACTIVE)


class AmendIn(BaseModel):
    field: str
    value: float | str | None = None
    reason: str = ""


@router.post("/{wid}/amend")
async def amend(wid: str, body: AmendIn,
                p: Person = Depends(signed_in)):
    """
    Correct a field on a signed job. The original stays on record next to
    the change, with who, when and why.
    """
    _writer(p)
    data = CompanyData(p)
    wo = await _load(data, wid)
    if wo["status"] not in R.SIGNED:
        raise Problem(400, Msg("wo.err.amend_needs_signed"))
    _deny(R.may_amend(p, wo), "wo.err.cannot_amend")
    if body.field not in R.EDITABLE:
        raise Problem(400, Msg("err.not_allowed"))
    if not body.reason.strip():
        raise Problem(400, Msg("wo.err.need_reason"))
    fields, errors = R.check_fields({body.field: body.value})
    if body.field in ("complaint", "correction") and not fields[body.field]:
        errors.append(Msg("err.required", field=Msg("field." + body.field)))
    if errors:
        raise Problem(400, {"errors": errors})
    new = fields[body.field]
    if wo.get(body.field) == new:
        raise Problem(400, Msg("wo.err.no_change"))
    a = {**_stamp(p), "field": body.field, "before": wo.get(body.field),
         "after": new, "reason": body.reason.strip()}
    return await _save(data, p, wo, "wo.amended",
                       changes={body.field: new}, push={"amendments": a},
                       before={body.field: wo.get(body.field)},
                       after={body.field: new, "reason": a["reason"]},
                       expect_status=wo["status"])
