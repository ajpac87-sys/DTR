"""
The change log: who changed what, when, in each company.

Each entry carries a fingerprint (a SHA-256 hash) of its own contents plus
the previous entry's fingerprint, forming a chain. Change or delete any old
entry and every fingerprint after it stops matching, so tampering shows.
`verify_chain()` walks the chain and says where it breaks, if anywhere.

Changes are logged. Reads and browsing are not (owner's rule, carried over
from InMotion).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .tenancy import Principal

GENESIS = "0" * 64
HASHED_FIELDS = ("org_id", "seq", "at", "actor_user_id", "actor_name",
                 "actor_role", "action", "record_type", "record_id",
                 "before", "after", "prev_hash")


def _canon(value: Any) -> Any:
    if isinstance(value, datetime):
        # The database keeps times to the millisecond, so hash them that way
        # or a record read back would never match its own fingerprint.
        v = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        v = v.replace(microsecond=v.microsecond // 1000 * 1000)
        return v.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def chain_hash(entry: dict[str, Any]) -> str:
    payload = {k: _canon(entry.get(k)) for k in HASHED_FIELDS}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_chain(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Check a company's log, oldest first. Says where it breaks, if it does."""
    prev = GENESIS
    for i, e in enumerate(sorted(entries, key=lambda x: x["seq"])):
        if e["seq"] != i + 1:
            return {"ok": False, "at_seq": i + 1,
                    "why": "An entry is missing from the sequence."}
        if e.get("prev_hash") != prev:
            return {"ok": False, "at_seq": e["seq"],
                    "why": "This entry does not link to the one before it."}
        if chain_hash(e) != e.get("hash"):
            return {"ok": False, "at_seq": e["seq"],
                    "why": "This entry was changed after it was written."}
        prev = e["hash"]
    return {"ok": True, "entries": len(entries)}


async def record(tdb, p: Principal, action: str, record_type: str,
                 record_id: str, before: dict | None = None,
                 after: dict | None = None) -> dict:
    """
    Append one entry to a company's log.

    The company is the one `tdb` writes to. The "who did it" fields come
    from `p`, which may be the Apex operator acting on a customer company:
    logged truthfully as Apex, in the customer's own log.
    """
    from pymongo.errors import DuplicateKeyError

    for _ in range(5):
        last = await tdb.find("audit_log", sort=[("seq", -1)], limit=1)
        seq = last[0]["seq"] + 1 if last else 1
        entry = {
            "entry_id": uuid.uuid4().hex, "org_id": tdb.p.org_id, "seq": seq,
            "at": datetime.now(timezone.utc),
            "actor_user_id": p.user_id, "actor_name": p.name,
            "actor_role": p.role.value, "action": action,
            "record_type": record_type, "record_id": record_id,
            "before": before, "after": after,
            "prev_hash": last[0]["hash"] if last else GENESIS,
        }
        entry["hash"] = chain_hash(entry)
        try:
            return await tdb.insert("audit_log", entry)
        except DuplicateKeyError:
            continue        # someone else wrote the same number; try again
    raise RuntimeError("Could not write to the change log. Try again.")
