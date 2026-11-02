"""
DTR: shop maintenance and parts inventory for trucking fleets.

This file only wires the pieces together. Each part of the system lives in
its own file; the screens live in dtr/static as ordinary HTML and JavaScript.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import accounts, audit
from .assets.routes import router as assets_router
from .auth import current_principal
from .db import ScopeError, TenantDB, ensure_indexes
from .regulatory import REGISTER
from .tenancy import READ_AUDIT, Principal

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    await accounts.bootstrap_operator()
    yield


app = FastAPI(title="DTR", lifespan=lifespan)
app.include_router(accounts.router)
app.include_router(assets_router)


@app.exception_handler(ScopeError)
async def _scope_error(request, exc):
    # A write that could have landed in the wrong company. Refused, plainly.
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "Not allowed for this account."}, 403)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/audit")
async def audit_log(limit: int = 200,
                    p: Principal = Depends(current_principal)):
    if not p.may(READ_AUDIT):
        raise HTTPException(403, "Only the company admin can read the log.")
    rows = await TenantDB(p).find("audit_log", sort=[("seq", -1)],
                                  limit=max(1, min(limit, 1000)))
    return {"entries": rows}


@app.get("/api/audit/verify")
async def audit_verify(p: Principal = Depends(current_principal)):
    if not p.may(READ_AUDIT):
        raise HTTPException(403, "Only the company admin can read the log.")
    return audit.verify_chain(await TenantDB(p).find("audit_log"))


@app.get("/api/regulatory")
async def regulatory(p: Principal = Depends(current_principal)):
    return {"register": REGISTER}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
