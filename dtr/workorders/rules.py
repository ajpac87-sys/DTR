"""
Work orders: the rules.

A work order is one job on one unit: what was wrong (complaint), why
(cause), what was done (correction), who worked it and for how long, what
parts and outside work it took, and the tech's sign-off.

THE STATUS LADDER
    open -> in progress -> waiting on parts -> complete -> closed
Open, in progress and waiting on parts can move back and forth freely. A job
becomes COMPLETE only by a tech's sign-off. A shop manager reviews it and
CLOSES it. A job that shouldn't exist (a duplicate) is CANCELLED with a reason.

SIGNED WORK IS NOT EDITED. Once signed off, nothing on the job is silently
changed. A correction is an AMENDMENT: what changed, from what, to what, why,
who, and when, kept alongside the original. A labor or parts line is never
deleted; it is voided with a reason and stays visible.

A WORK ORDER DOES NOT DECIDE WHETHER A TRUCK MAY RUN. That is the DVIR repair
certification (49 CFR 396.11), coming in the next step. Closing a job will
produce that certification for a linked defect; it never clears a unit on
its own say-so.

No database or web code here, so the rules can be tested directly.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from ..i18n import Msg
from ..tenancy import Principal, Role

OPEN = "open"
IN_PROGRESS = "in_progress"
WAITING_PARTS = "waiting_parts"
COMPLETE = "complete"
CLOSED = "closed"
CANCELLED = "cancelled"

STATUSES = (OPEN, IN_PROGRESS, WAITING_PARTS, COMPLETE, CLOSED, CANCELLED)
ACTIVE = (OPEN, IN_PROGRESS, WAITING_PARTS)    # still being worked
SIGNED = (COMPLETE, CLOSED)                    # changes need an amendment

# Moves a person can make by tapping a status. COMPLETE, CLOSED and
# CANCELLED each have their own action with its own checks.
MOVES = {
    OPEN: {IN_PROGRESS, WAITING_PARTS},
    IN_PROGRESS: {OPEN, WAITING_PARTS},
    WAITING_PARTS: {OPEN, IN_PROGRESS},
}

PRIORITIES = ("urgent", "high", "normal", "low")
PRIORITY_RANK = {p: i for i, p in enumerate(PRIORITIES)}

# Where the job came from (brief 5.3). DVIR and PM jobs will be raised
# automatically in later steps; for now any of these can be chosen by hand.
SOURCES = ("manual", "dvir_defect", "pm", "breakdown", "roadside",
           "inspection")

CATEGORIES = ("engine", "brakes", "tires_wheels", "electrical", "lighting",
              "suspension_steering", "drivetrain", "cooling", "fuel",
              "exhaust_aftertreatment", "hvac", "body_frame", "coupling",
              "refrigeration", "pm_service", "inspection", "other")

# Fields that can be edited before sign-off, and amended after.
TEXT_FIELDS = ("complaint", "cause", "correction")
EDITABLE = TEXT_FIELDS + ("priority", "category", "source", "source_ref",
                          "odometer", "engine_hours")

MAX_TEXT = 4000


# --- Who may do what ---------------------------------------------------------

SHOP_LEADS = {Role.SHOP_MANAGER, Role.ADMIN}
TECHS = {Role.MECHANIC, Role.SHOP_MANAGER, Role.ADMIN}
ANY_STAFF = {Role.MECHANIC, Role.SHOP_MANAGER, Role.FLEET_MANAGER, Role.ADMIN}


def may_create(p: Principal) -> bool:
    return p.role in ANY_STAFF


def may_work(p: Principal) -> bool:
    """Change status, add parts, outside work, own labor."""
    return p.role in TECHS


def may_note(p: Principal) -> bool:
    """Notes and photos. A fleet manager can add these too."""
    return p.role in ANY_STAFF


def may_lead(p: Principal) -> bool:
    """Assign techs, log labor for others, close, cancel, amend."""
    return p.role in SHOP_LEADS


def may_sign(p: Principal, wo: dict) -> bool:
    """
    The person signing must have worked the job: assigned to it or logged
    labor on it. A shop manager or admin may sign any job (they supervise).
    """
    if p.role in SHOP_LEADS:
        return True
    if p.role is not Role.MECHANIC:
        return False
    if any(a["user_id"] == p.user_id for a in wo.get("assigned", [])):
        return True
    return any(l["user_id"] == p.user_id and not l.get("voided")
               for l in wo.get("labor", []))


def may_amend(p: Principal, wo: dict) -> bool:
    if p.role in SHOP_LEADS:
        return True
    so = wo.get("signoff") or {}
    return so.get("user_id") == p.user_id


# --- Checking what was entered ----------------------------------------------

def clean_text(v) -> str | None:
    v = str(v or "").strip()
    return v[:MAX_TEXT] or None


def number(value, field: str, *, allow_zero=True, maximum=None):
    """Returns (number or None, error Msg or None)."""
    if value in (None, ""):
        return None, None
    try:
        n = float(str(value).replace(",", "").strip())
    except ValueError:
        return None, Msg("err.not_a_number", field=Msg("field." + field))
    if n < 0 or (n == 0 and not allow_zero):
        return None, Msg("err.must_be_positive", field=Msg("field." + field))
    if maximum is not None and n > maximum:
        return None, Msg("err.too_large", field=Msg("field." + field),
                         max=maximum)
    return n, None


def check_fields(data: dict) -> tuple[dict, list]:
    """Clean the editable fields that were sent. Returns (clean, errors)."""
    out, errors = {}, []
    for f in TEXT_FIELDS + ("source_ref",):
        if f in data:
            out[f] = clean_text(data[f])
    if "priority" in data:
        if data["priority"] not in PRIORITIES:
            errors.append(Msg("err.bad_choice", field=Msg("field.priority")))
        out["priority"] = data["priority"]
    if "category" in data:
        if data["category"] not in CATEGORIES:
            errors.append(Msg("err.bad_choice", field=Msg("field.category")))
        out["category"] = data["category"]
    if "source" in data:
        if data["source"] not in SOURCES:
            errors.append(Msg("err.bad_choice", field=Msg("field.source")))
        out["source"] = data["source"]
    for f in ("odometer", "engine_hours"):
        if f in data:
            n, e = number(data[f], f, maximum=10_000_000)
            if e:
                errors.append(e)
            out[f] = n
    return out, errors


def check_labor(data: dict, today: date | None = None) -> tuple[dict, list]:
    today = today or datetime.now(timezone.utc).date()
    errors = []
    hours, e = number(data.get("hours"), "hours", allow_zero=False,
                      maximum=24)
    if e:
        errors.append(e)
    elif hours is None:
        errors.append(Msg("err.required", field=Msg("field.hours")))
    d = data.get("date") or today.isoformat()
    try:
        worked = date.fromisoformat(str(d)[:10])
        # A day ahead is allowed: the shop's clock and the server's (UTC)
        # can disagree around midnight.
        if (worked - today).days > 1:
            errors.append(Msg("err.date_future"))
    except ValueError:
        errors.append(Msg("err.bad_date"))
        worked = today
    return {"hours": hours, "date": worked.isoformat(),
            "note": clean_text(data.get("note"))}, errors


def check_part(data: dict) -> tuple[dict, list]:
    errors = []
    desc = clean_text(data.get("description"))
    pn = clean_text(data.get("part_number"))
    if not desc and not pn:
        errors.append(Msg("err.part_needs_name"))
    qty, e = number(data.get("qty"), "qty", allow_zero=False,
                    maximum=100_000)
    if e:
        errors.append(e)
    elif qty is None:
        errors.append(Msg("err.required", field=Msg("field.qty")))
    cost, e = number(data.get("unit_cost"), "unit_cost", maximum=1_000_000)
    if e:
        errors.append(e)
    return {"part_number": pn, "description": desc, "qty": qty,
            "unit_cost": cost}, errors


def check_vendor(data: dict) -> tuple[dict, list]:
    errors = []
    vendor = clean_text(data.get("vendor"))
    if not vendor:
        errors.append(Msg("err.required", field=Msg("field.vendor")))
    amount, e = number(data.get("amount"), "amount", maximum=10_000_000)
    if e:
        errors.append(e)
    return {"vendor": vendor,
            "invoice_number": clean_text(data.get("invoice_number")),
            "description": clean_text(data.get("description")),
            "amount": amount}, errors


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def check_signoff(p: Principal, wo: dict, typed_name: str) -> list:
    """
    What stops this person signing this job off now.

    The signer TYPES their own name. Nothing is pre-filled: a sign-off is an
    attestation, and one tap on a pre-filled box would automate it.
    """
    errors = []
    if wo["status"] not in ACTIVE:
        errors.append(Msg("wo.err.not_open"))
    if not may_sign(p, wo):
        errors.append(Msg("wo.err.cannot_sign"))
    if not wo.get("correction"):
        errors.append(Msg("wo.err.need_correction"))
    if not typed_name or _norm_name(typed_name) != _norm_name(p.name):
        errors.append(Msg("wo.err.name_mismatch", name=p.name))
    return errors


def warnings_at_signoff(wo: dict) -> list:
    """Worth a look, but doesn't stop the sign-off."""
    w = []
    if not live(wo.get("labor", [])):
        w.append(Msg("wo.warn.no_labor"))
    if not wo.get("cause"):
        w.append(Msg("wo.warn.no_cause"))
    return w


# --- Arithmetic ----------------------------------------------------------------

def live(lines: list) -> list:
    return [l for l in lines if not l.get("voided")]


def totals(wo: dict) -> dict:
    labor = sum(l["hours"] or 0 for l in live(wo.get("labor", [])))
    parts = sum((l["qty"] or 0) * (l["unit_cost"] or 0)
                for l in live(wo.get("parts", [])))
    vendor = sum(l["amount"] or 0 for l in live(wo.get("vendor", [])))
    return {"labor_hours": round(labor, 2), "parts_cost": round(parts, 2),
            "vendor_cost": round(vendor, 2),
            "cost_without_labor": round(parts + vendor, 2)}


def sort_key(wo: dict):
    """Board order: worst first, then oldest first."""
    return (PRIORITY_RANK.get(wo.get("priority"), 9), wo.get("number", 0))
