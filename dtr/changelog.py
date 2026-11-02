"""
The change log: every change in a company, who made it, and when.

Each entry is sealed with a SHA-256 fingerprint that covers its own contents
and the seal of the entry before it. Edit or remove an old entry and every
seal after it stops matching, so `check()` shows where the log was altered.

Changes are logged. Reading and browsing are not.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .access import Person

FIRST_SEAL = "start"
SEALED = ("org_id", "seq", "at", "actor_user_id", "actor_name", "actor_role",
          "action", "record_type", "record_id", "before", "after", "prev_seal")


def _plain(value):
    """Turn a value into plain JSON the same way every time."""
    if isinstance(value, datetime):
        # The database keeps milliseconds, so the seal does too.
        v = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{v.microsecond // 1000:03d}Z"
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def seal(entry: dict) -> str:
    body = json.dumps({k: _plain(entry.get(k)) for k in SEALED},
                      sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def check(entries: list[dict]) -> dict:
    """Walk a company's log from the first entry and report the first break."""
    expected_prev = FIRST_SEAL
    ordered = sorted(entries, key=lambda e: e["seq"])
    for n, e in enumerate(ordered, start=1):
        if e["seq"] != n:
            return {"ok": False, "at_seq": n,
                    "why": "An entry is missing from the sequence."}
        if e.get("prev_seal") != expected_prev:
            return {"ok": False, "at_seq": n,
                    "why": "This entry does not link to the one before it."}
        if seal(e) != e.get("seal"):
            return {"ok": False, "at_seq": n,
                    "why": "This entry was changed after it was written."}
        expected_prev = e["seal"]
    return {"ok": True, "entries": len(ordered)}


async def write(data, who: Person, action: str, record_type: str,
                record_id: str, before: dict | None = None,
                after: dict | None = None) -> dict:
    """
    Add one entry to the log of the company `data` writes to. `who` fills in
    who did it; for Apex working on a customer company, that's Apex, named
    as such in the customer's own log.
    """
    from pymongo.errors import DuplicateKeyError

    for _attempt in range(5):
        newest = await data.find("change_log", sort=[("seq", -1)], limit=1)
        entry = {
            "entry_id": uuid.uuid4().hex, "org_id": data.person.org_id,
            "seq": newest[0]["seq"] + 1 if newest else 1,
            "at": datetime.now(timezone.utc),
            "actor_user_id": who.user_id, "actor_name": who.name,
            "actor_role": who.role.value, "action": action,
            "record_type": record_type, "record_id": record_id,
            "before": before, "after": after,
            "prev_seal": newest[0]["seal"] if newest else FIRST_SEAL,
        }
        entry["seal"] = seal(entry)
        try:
            return await data.insert("change_log", entry)
        except DuplicateKeyError:
            continue        # two changes at once took the same number; retry
    raise RuntimeError("The change log is busy. Try again.")
