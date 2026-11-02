"""
Sign-in, companies, and people.

Apex (the platform operator) sets up each customer company and its first
admin. From there the company adds its own people. Nobody can give a role
above their own. There is no "act as another user" anywhere: doing that
would create records signed by someone who didn't do the work.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field

from . import changelog
from .auth import signed_in, encode_token
from .db import CompanyData, db
from .i18n import LANGUAGES, Msg, Problem, pick
from .passwords import hash_password, password_ok, verify_password
from .access import MANAGE_PEOPLE, Person, Role, can_grant

router = APIRouter(prefix="/api")

# A real hash to compare against when the email isn't found, so a wrong email
# takes as long as a wrong password and can't be used to discover accounts.
_DUMMY_HASH = hash_password(uuid.uuid4().hex)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public(u: dict) -> dict:
    return {"user_id": u["user_id"], "name": u["name"], "email": u["email"],
            "role": u["role"], "org_id": u.get("org_id"),
            "active": u.get("active", True),
            "language": u.get("language") or "en"}


def _person(u: dict) -> Person:
    return Person(user_id=u["user_id"], org_id=u.get("org_id"),
                     role=Role(u["role"]), name=u["name"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


@router.post("/auth/login")
async def login(body: LoginIn):
    u = await db().users.find_one({"email": body.email.lower()}, {"_id": 0})
    ok = verify_password(body.password, u["password_hash"] if u
                         else _DUMMY_HASH)
    if not u or not ok:
        raise Problem(401, Msg("err.bad_login"))
    if not u.get("active", True):
        raise Problem(401, Msg("err.account_off"))
    org = None
    if u.get("org_id"):
        org = await db().orgs.find_one({"org_id": u["org_id"]}, {"_id": 0})
    return {"token": encode_token(_person(u)), "user": _public(u),
            "org": org}


@router.get("/me")
async def me(p: Person = Depends(signed_in)):
    u = await db().users.find_one({"user_id": p.user_id}, {"_id": 0})
    org = None
    if p.org_id:
        org = await db().orgs.find_one({"org_id": p.org_id}, {"_id": 0})
    return {"user": _public(u), "org": org,
            "can": sorted(_perms(p)), "languages": LANGUAGES}


class PrefsIn(BaseModel):
    language: str


@router.patch("/me")
async def set_prefs(body: PrefsIn, p: Person = Depends(signed_in)):
    """A person's own language. Saved so it follows them to any phone."""
    lang = pick(body.language)
    await db().users.update_one({"user_id": p.user_id},
                                {"$set": {"language": lang}})
    return {"language": lang}


def _perms(p: Person) -> set[str]:
    from .access import PERMISSIONS
    return set(PERMISSIONS.get(p.role, frozenset()))


# --- People in a company ----------------------------------------------------

class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    role: Role
    password: str = Field(max_length=256)
    language: str | None = None


async def _create_user(org_id: str | None, body: UserIn) -> dict:
    if not password_ok(body.password):
        raise Problem(400, Msg("err.password_short"))
    email = body.email.lower()
    if await db().users.find_one({"email": email}, {"_id": 1}):
        raise Problem(409, Msg("err.email_taken"))
    u = {"user_id": uuid.uuid4().hex, "org_id": org_id,
         "name": body.name.strip(), "email": email, "role": body.role.value,
         "password_hash": hash_password(body.password), "active": True,
         "language": pick(body.language),
         "created_at": _now()}
    await db().users.insert_one(dict(u))
    return u


@router.get("/users")
async def list_users(p: Person = Depends(signed_in)):
    if p.is_operator:
        raise Problem(400, Msg("err.operator_open_company"))
    rows = await db().users.find({"org_id": p.org_id}, {"_id": 0}
                                 ).sort("name", 1).to_list(None)
    return {"users": [_public(u) for u in rows],
            "may_add": [r.value for r in Role if can_grant(p.role, r)]
            if p.may(MANAGE_PEOPLE) else []}


@router.post("/users", status_code=201)
async def add_user(body: UserIn, p: Person = Depends(signed_in)):
    if not p.may(MANAGE_PEOPLE) or not can_grant(p.role, body.role):
        raise Problem(403, Msg("err.cannot_add_role",
                                 actor=Msg("role." + p.role.value),
                                 target=Msg("role." + body.role.value)))
    u = await _create_user(p.org_id, body)
    await changelog.write(CompanyData(p), p, "user.created", "user", u["user_id"],
                       after=_public(u))
    return _public(u)


# --- Apex console: companies ------------------------------------------------

class OrgIn(BaseModel):
    company_name: str = Field(min_length=1, max_length=120)
    admin_name: str = Field(min_length=1, max_length=80)
    admin_email: EmailStr
    admin_password: str = Field(max_length=256)


def _operator_only(p: Person) -> None:
    if not p.is_operator:
        raise Problem(403, Msg("err.operator_only"))


@router.get("/operator/orgs")
async def list_orgs(p: Person = Depends(signed_in)):
    _operator_only(p)
    orgs = await db().orgs.find({}, {"_id": 0}).sort("name", 1).to_list(None)
    for o in orgs:
        o["units"] = await CompanyData(p).count(
            "assets", {"org_id": o["org_id"], "status": "active"})
        o["people"] = await db().users.count_documents({"org_id": o["org_id"]})
    return {"orgs": orgs}


@router.post("/operator/orgs", status_code=201)
async def create_org(body: OrgIn, p: Person = Depends(signed_in)):
    _operator_only(p)
    org = {"org_id": uuid.uuid4().hex, "name": body.company_name.strip(),
           "created_at": _now(), "created_by": p.user_id}
    await db().orgs.insert_one(dict(org))
    admin = await _create_user(org["org_id"], UserIn(
        name=body.admin_name, email=body.admin_email, role=Role.ADMIN,
        password=body.admin_password))
    # Logged in the CUSTOMER's own log, truthfully attributed to Apex.
    as_admin = CompanyData(_person(admin))
    await changelog.write(as_admin, p, "org.created",
                       "org", org["org_id"], after={"name": org["name"]})
    await changelog.write(as_admin, p, "user.created",
                       "user", admin["user_id"], after=_public(admin))
    return {"org": org, "admin": _public(admin)}


# --- First Apex account -----------------------------------------------------

async def bootstrap_operator() -> str | None:
    """
    Create the first Apex sign-in from the OPERATOR_EMAIL and
    OPERATOR_PASSWORD settings, only if no operator exists yet. Does nothing
    once one exists, so changing those settings later changes nothing.
    """
    email = (os.environ.get("OPERATOR_EMAIL") or "").strip().lower()
    pw = os.environ.get("OPERATOR_PASSWORD") or ""
    if not email or not password_ok(pw):
        return None
    if await db().users.find_one({"role": Role.PLATFORM_OPERATOR.value},
                                 {"_id": 1}):
        return None
    await _create_user(None, UserIn(
        name=os.environ.get("OPERATOR_NAME") or "Apex", email=email,
        role=Role.PLATFORM_OPERATOR, password=pw))
    return email
