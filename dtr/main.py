"""
DTR: shop maintenance and parts inventory for trucking fleets.

This file only wires the pieces together. Each part of the system lives in
its own file; the screens live in dtr/static as ordinary HTML and JavaScript.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import accounts, changelog
from .assets.routes import router as assets_router
from .workorders.routes import router as workorders_router
from .auth import signed_in
from .db import WrongCompany, CompanyData, ensure_indexes
from .i18n import Msg, Problem, pick, tr
from .regulatory import REGISTER
from .access import READ_AUDIT, Person

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    await accounts.bootstrap_operator()
    yield


app = FastAPI(title="DTR", lifespan=lifespan)
app.include_router(accounts.router)
app.include_router(assets_router)
app.include_router(workorders_router)


def _lang(request: Request) -> str:
    return pick(request.headers.get("x-lang"))


@app.exception_handler(Problem)
async def _problem(request: Request, exc: Problem):
    return JSONResponse({"detail": tr(exc.detail, _lang(request))},
                        exc.status)


@app.exception_handler(WrongCompany)
async def _scope_error(request: Request, exc: WrongCompany):
    # A write that could have landed in the wrong company. Refused, plainly.
    return JSONResponse(
        {"detail": tr(Msg("err.not_allowed"), _lang(request))}, 403)


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, exc: RequestValidationError):
    # A form field the server can't accept (bad email, missing name). Says
    # which field, in the reader's language.
    lang = _lang(request)
    fields = []
    for e in exc.errors():
        name = str(e.get("loc", [""])[-1])
        fields.append(tr(Msg("field." + name), lang)
                      if name else "")
    return JSONResponse({"detail": {"errors": [
        tr(Msg("err.check_field", field=f), lang) for f in fields]}}, 422)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/audit")
async def audit_log(limit: int = 200,
                    p: Person = Depends(signed_in)):
    if not p.may(READ_AUDIT):
        raise Problem(403, Msg("err.admin_only_log"))
    rows = await CompanyData(p).find("change_log", sort=[("seq", -1)],
                                  limit=max(1, min(limit, 1000)))
    return {"entries": rows}


@app.get("/api/audit/verify")
async def audit_verify(p: Person = Depends(signed_in)):
    if not p.may(READ_AUDIT):
        raise Problem(403, Msg("err.admin_only_log"))
    return changelog.check(await CompanyData(p).find("change_log"))


@app.get("/api/regulatory")
async def regulatory(p: Person = Depends(signed_in)):
    return {"register": REGISTER}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
