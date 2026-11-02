"""
Login tokens.

A token is a signed note that says "this is user X, in company Y, with role
Z". The server signs it with a secret only it knows (the JWT_SECRET setting on
Railway), so a browser cannot forge or edit one. Who you are and which company
you belong to come from this note and nowhere else.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .i18n import Msg, Problem
from .access import Person, Role

ISSUER = "dtr"
TOKEN_HOURS = 12
_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    s = os.environ.get("JWT_SECRET", "")
    # Refuse to run with a missing or toy secret rather than sign tokens
    # anyone could forge.
    if len(s) < 32:
        raise RuntimeError(
            "JWT_SECRET is missing or shorter than 32 characters. Set it in "
            "the Railway service's Variables tab.")
    return s


def encode_token(p: Person, hours: int = TOKEN_HOURS) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER, "sub": p.user_id, "org": p.org_id,
        "role": p.role.value, "name": p.name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    return jwt.encode(claims, _secret(), algorithm="HS256")


def person_from_claims(claims: dict[str, Any]) -> Person:
    try:
        role = Role(claims["role"])
    except (KeyError, ValueError):
        raise ValueError("token has no valid role")
    return Person(user_id=str(claims.get("sub") or ""),
                     org_id=claims.get("org") or None,
                     role=role, name=str(claims.get("name") or ""))


def decode_token(token: str) -> Person:
    claims = jwt.decode(token, _secret(), algorithms=["HS256"],
                        issuer=ISSUER, options={"require": ["exp", "sub"]})
    return person_from_claims(claims)


async def signed_in(
        cred: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> Person:
    if cred is None:
        raise Problem(401, Msg("err.sign_in_first"))
    try:
        p = decode_token(cred.credentials)
    except Exception:
        raise Problem(401, Msg("err.session_expired"))
    # A token stays valid until it expires, so check the account was not
    # switched off in the meantime.
    from .db import db
    user = await db().users.find_one({"user_id": p.user_id},
                                     {"_id": 0, "active": 1})
    if not user or not user.get("active", True):
        raise Problem(401, Msg("err.account_off"))
    return p
