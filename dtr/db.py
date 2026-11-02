"""
The database connection and the ONLY way company data is read or written.

Every collection holding a company's records must be listed in
TENANT_SCOPED_COLLECTIONS. `TenantDB` refuses any collection not on the list,
and the test suite checks every listed collection for leaks between
companies. Adding a collection without listing it fails loudly instead of
leaking quietly.
"""
from __future__ import annotations

import os
from typing import Any

from .tenancy import DENY_ALL, Principal, scoped

TENANT_SCOPED_COLLECTIONS = frozenset({
    "assets",
    "audit_log",
    "counters",        # per-company running numbers (WO-0001, ...)
    "work_orders",
    "wo_photos",
})

# Not company-scoped: looked up across companies by the sign-in code, and
# only ever returned to a caller after their own company check.
GLOBAL_COLLECTIONS = frozenset({"orgs", "users"})

_db = None


def db():
    global _db
    if _db is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        url = os.environ.get("MONGO_URL")
        if not url:
            raise RuntimeError("MONGO_URL is not set.")
        _db = AsyncIOMotorClient(url)[os.environ.get("DB_NAME", "dtr")]
    return _db


def set_db(database) -> None:
    """Point the app at a given database. Used by the tests."""
    global _db
    _db = database


async def ensure_indexes() -> None:
    d = db()
    await d.users.create_index("user_id", unique=True)
    await d.users.create_index("email", unique=True)
    await d.orgs.create_index("org_id", unique=True)
    await d.assets.create_index("asset_id", unique=True)
    # One unit number per company. Two companies may both have a truck 101.
    await d.assets.create_index([("org_id", 1), ("unit_number_key", 1)],
                                unique=True)
    await d.audit_log.create_index([("org_id", 1), ("seq", 1)], unique=True)
    await d.counters.create_index([("org_id", 1), ("name", 1)], unique=True)
    await d.work_orders.create_index("work_order_id", unique=True)
    await d.work_orders.create_index([("org_id", 1), ("number", 1)],
                                     unique=True)
    await d.work_orders.create_index([("org_id", 1), ("asset_id", 1)])
    await d.wo_photos.create_index("photo_id", unique=True)


class ScopeError(RuntimeError):
    pass


class TenantDB:
    """
    Company data, seen through one person's login.

    Reads are limited to that person's company. Writes stamp the company from
    the login, never from the request. The Apex operator can read across
    companies but cannot write through this class at all; operator changes
    need an explicit target company and their own audited route (not built
    yet), so they can never land in the wrong company by accident.
    """

    def __init__(self, principal: Principal):
        self.p = principal

    def _col(self, name: str):
        if name not in TENANT_SCOPED_COLLECTIONS:
            raise ScopeError(f"{name} is not a registered company collection")
        return db()[name]

    def _writer_org(self) -> str:
        if self.p.is_operator or not self.p.org_id:
            raise ScopeError("writes need a home company")
        return self.p.org_id

    async def find(self, name: str, cond: dict | None = None, *,
                   sort: list | None = None, limit: int = 0) -> list[dict]:
        q = scoped(self.p, cond)
        if q == DENY_ALL:
            return []
        cur = self._col(name).find(q, {"_id": 0})
        if sort:
            cur = cur.sort(sort)
        if limit:
            cur = cur.limit(limit)
        return await cur.to_list(None)

    async def find_one(self, name: str, cond: dict) -> dict | None:
        q = scoped(self.p, cond)
        if q == DENY_ALL:
            return None
        return await self._col(name).find_one(q, {"_id": 0})

    async def count(self, name: str, cond: dict | None = None) -> int:
        q = scoped(self.p, cond)
        if q == DENY_ALL:
            return 0
        return await self._col(name).count_documents(q)

    async def insert(self, name: str, doc: dict[str, Any]) -> dict:
        doc = {**doc, "org_id": self._writer_org()}
        await self._col(name).insert_one(dict(doc))
        return doc

    async def insert_many(self, name: str, docs: list[dict]) -> list[dict]:
        org = self._writer_org()
        docs = [{**d, "org_id": org} for d in docs]
        if docs:
            await self._col(name).insert_many([dict(d) for d in docs])
        return docs

    async def update(self, name: str, cond: dict, changes: dict | None = None,
                     push: dict | None = None) -> bool:
        """
        Change one record in this company. `changes` sets fields; `push`
        adds to lists. Returns False if no record matched (wrong company,
        or the condition, such as the expected status, no longer holds).
        """
        changes = changes or {}
        if "org_id" in changes or "org_id" in (push or {}):
            raise ScopeError("a record cannot be moved to another company")
        q = {"$and": [{"org_id": self._writer_org()}, cond]}
        doc = {}
        if changes:
            doc["$set"] = changes
        if push:
            doc["$push"] = push
        if not doc:
            return await self._col(name).count_documents(q) == 1
        res = await self._col(name).update_one(q, doc)
        return res.matched_count == 1

    async def next_number(self, counter: str) -> int:
        """The next running number for this company (1, 2, 3...)."""
        from pymongo import ReturnDocument
        org = self._writer_org()
        doc = await self._col("counters").find_one_and_update(
            {"org_id": org, "name": counter}, {"$inc": {"value": 1}},
            upsert=True, return_document=ReturnDocument.AFTER)
        return doc["value"]
