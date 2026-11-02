"""
The database, and the one doorway to a company's records: `CompanyData`.

Every collection that holds a company's records is listed in
COMPANY_COLLECTIONS. CompanyData refuses any collection not on that list,
and the tests check every listed collection for leaks between companies, so
a new collection that isn't listed fails loudly instead of leaking quietly.
"""
from __future__ import annotations

import os

from .access import NOTHING, Person, within_company

COMPANY_COLLECTIONS = frozenset({
    "assets",          # trucks and trailers
    "change_log",
    "counters",        # running numbers per company (WO-0001, WO-0002...)
    "work_orders",
    "wo_photos",
})

# Shared across companies: sign-in looks people up by email before it knows
# their company. Code reads these directly and checks the company itself.
SHARED_COLLECTIONS = frozenset({"orgs", "users"})

_database = None


def db():
    global _database
    if _database is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        url = os.environ.get("MONGO_URL")
        if not url:
            raise RuntimeError("MONGO_URL is not set.")
        _database = AsyncIOMotorClient(url)[os.environ.get("DB_NAME", "dtr")]
    return _database


def set_db(database) -> None:
    """Point the app at another database (the tests use an in-memory one)."""
    global _database
    _database = database


async def ensure_indexes() -> None:
    d = db()
    await d.users.create_index("user_id", unique=True)
    await d.users.create_index("email", unique=True)
    await d.orgs.create_index("org_id", unique=True)
    await d.assets.create_index("asset_id", unique=True)
    # One unit number per company; two companies can each have a truck 101.
    await d.assets.create_index([("org_id", 1), ("unit_number_key", 1)],
                                unique=True)
    await d.change_log.create_index([("org_id", 1), ("seq", 1)], unique=True)
    await d.counters.create_index([("org_id", 1), ("name", 1)], unique=True)
    await d.work_orders.create_index("work_order_id", unique=True)
    await d.work_orders.create_index([("org_id", 1), ("number", 1)],
                                     unique=True)
    await d.work_orders.create_index([("org_id", 1), ("asset_id", 1)])
    await d.wo_photos.create_index("photo_id", unique=True)


class WrongCompany(RuntimeError):
    """A read or write that could cross from one company into another."""


class CompanyData:
    """
    A company's records, as one signed-in person may reach them.

    Reads stay inside that person's company. Writes are stamped with the
    company from the sign-in, never from the request. Apex can read across
    companies but can't write through here at all: a change by Apex needs its
    own route that names the company on purpose and logs it.
    """

    def __init__(self, person: Person):
        self.person = person

    def _collection(self, name: str):
        if name not in COMPANY_COLLECTIONS:
            raise WrongCompany(f"{name} is not a company collection")
        return db()[name]

    def _home(self) -> str:
        if self.person.is_operator or not self.person.org_id:
            raise WrongCompany("only someone in the company can change it")
        return self.person.org_id

    async def find(self, name: str, cond: dict | None = None, *,
                   sort: list | None = None, limit: int = 0) -> list[dict]:
        q = within_company(self.person, cond)
        if q == NOTHING:
            return []
        cursor = self._collection(name).find(q, {"_id": 0})
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(None)

    async def find_one(self, name: str, cond: dict) -> dict | None:
        q = within_company(self.person, cond)
        if q == NOTHING:
            return None
        return await self._collection(name).find_one(q, {"_id": 0})

    async def count(self, name: str, cond: dict | None = None) -> int:
        q = within_company(self.person, cond)
        if q == NOTHING:
            return 0
        return await self._collection(name).count_documents(q)

    async def insert(self, name: str, doc: dict) -> dict:
        doc = {**doc, "org_id": self._home()}
        await self._collection(name).insert_one(dict(doc))
        return doc

    async def insert_many(self, name: str, docs: list[dict]) -> list[dict]:
        home = self._home()
        docs = [{**d, "org_id": home} for d in docs]
        if docs:
            await self._collection(name).insert_many([dict(d) for d in docs])
        return docs

    async def update(self, name: str, cond: dict, changes: dict | None = None,
                     push: dict | None = None) -> bool:
        """
        Change one record in this company: `changes` sets fields, `push` adds
        to lists. False when nothing matched (not this company's record, or
        a condition like the expected status no longer holds).
        """
        changes = changes or {}
        if "org_id" in changes or "org_id" in (push or {}):
            raise WrongCompany("a record can't move to another company")
        q = {"$and": [{"org_id": self._home()}, cond]}
        ops = {}
        if changes:
            ops["$set"] = changes
        if push:
            ops["$push"] = push
        if not ops:
            return await self._collection(name).count_documents(q) == 1
        result = await self._collection(name).update_one(q, ops)
        return result.matched_count == 1

    async def next_number(self, counter: str) -> int:
        """This company's next running number: 1, 2, 3..."""
        from pymongo import ReturnDocument
        doc = await self._collection("counters").find_one_and_update(
            {"org_id": self._home(), "name": counter}, {"$inc": {"value": 1}},
            upsert=True, return_document=ReturnDocument.AFTER)
        return doc["value"]
