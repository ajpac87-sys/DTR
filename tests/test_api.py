"""The running app: sign-in, roles, units, import, and company walls."""
import asyncio
import re
from pathlib import Path

import pytest

from conftest import OPERATOR, login
from dtr.db import SHARED_COLLECTIONS, COMPANY_COLLECTIONS, CompanyData
from dtr.access import Person, Role

TRUCK = {"asset_type": "power_unit", "unit_number": "101",
         "vin": "1M8GDM9AXKP042788", "make": "Freightliner",
         "model_year": 2019, "odometer": 412000}


def add(client, h, **kw):
    return client.post("/api/assets", headers=h, json={**TRUCK, **kw})


def test_wrong_password_refused(client):
    r = client.post("/api/auth/login", json={"email": OPERATOR["email"],
                                             "password": "nope-nope"})
    assert r.status_code == 401


def test_no_token_refused(client):
    assert client.get("/api/assets").status_code == 401


def test_admin_adds_and_reads_unit(client, two_fleets):
    a = two_fleets["a"]
    r = add(client, a)
    assert r.status_code == 201, r.text
    unit = r.json()["unit"]
    assert unit["odometer_by"] == "Admin A"
    assert client.get("/api/assets", headers=a).json()["units"][0][
        "unit_number"] == "101"


def test_same_unit_number_twice_refused(client, two_fleets):
    a = two_fleets["a"]
    add(client, a)
    r = add(client, a, unit_number=" 101 ")
    assert r.status_code == 400


def test_two_companies_may_both_have_truck_101(client, two_fleets):
    assert add(client, two_fleets["a"]).status_code == 201
    assert add(client, two_fleets["b"]).status_code == 201


def test_other_company_cannot_see_or_change_unit(client, two_fleets):
    a, b = two_fleets["a"], two_fleets["b"]
    uid = add(client, a).json()["unit"]["asset_id"]
    assert client.get("/api/assets", headers=b).json()["units"] == []
    assert client.get(f"/api/assets/{uid}", headers=b).status_code == 404
    r = client.patch(f"/api/assets/{uid}", headers=b, json={"make": "X"})
    assert r.status_code == 404
    r = client.post(f"/api/assets/{uid}/retire", headers=b,
                    json={"reason": "x"})
    assert r.status_code == 404
    assert client.get(f"/api/assets/{uid}", headers=a).json()[
        "make"] == "Freightliner"


def test_mechanic_can_view_but_not_change(client, two_fleets):
    a = two_fleets["a"]
    add(client, a)
    r = client.post("/api/users", headers=a, json={
        "name": "Joe Tech", "email": "joe@a.example.com", "role": "mechanic",
        "password": "mechanic-pass"})
    assert r.status_code == 201
    m = login(client, "joe@a.example.com", "mechanic-pass")
    assert len(client.get("/api/assets", headers=m).json()["units"]) == 1
    assert add(client, m, unit_number="102").status_code == 403
    r = client.post("/api/users", headers=m, json={
        "name": "X", "email": "x@a.example.com", "role": "mechanic",
        "password": "whatever-1"})
    assert r.status_code == 403


def test_shop_manager_cannot_make_admin(client, two_fleets):
    a = two_fleets["a"]
    client.post("/api/users", headers=a, json={
        "name": "Sam", "email": "sam@a.example.com", "role": "shop_manager",
        "password": "shop-pass-1"})
    s = login(client, "sam@a.example.com", "shop-pass-1")
    r = client.post("/api/users", headers=s, json={
        "name": "X", "email": "x@a.example.com", "role": "admin",
        "password": "whatever-1"})
    assert r.status_code == 403


def test_operator_reads_all_but_cannot_change(client, two_fleets):
    add(client, two_fleets["a"])
    add(client, two_fleets["b"], unit_number="900")
    ops = two_fleets["ops"]
    assert len(client.get("/api/assets", headers=ops).json()["units"]) == 2
    assert add(client, ops, unit_number="555").status_code == 403


def test_customer_cannot_use_apex_console(client, two_fleets):
    assert client.get("/api/operator/orgs",
                      headers=two_fleets["a"]).status_code == 403


def test_edit_is_logged_with_before_and_after(client, two_fleets):
    a = two_fleets["a"]
    uid = add(client, a).json()["unit"]["asset_id"]
    r = client.patch(f"/api/assets/{uid}", headers=a,
                     json={"make": "Kenworth"})
    assert r.status_code == 200
    log = client.get("/api/audit", headers=a).json()["entries"]
    assert log[0]["action"] == "unit.edited"
    assert log[0]["before"] == {"make": "Freightliner"}
    assert log[0]["after"] == {"make": "Kenworth"}
    assert client.get("/api/audit/verify", headers=a).json()["ok"]


def test_company_setup_logged_as_apex_in_customer_log(client, two_fleets):
    log = client.get("/api/audit", headers=two_fleets["a"]).json()["entries"]
    first = log[-1]
    assert first["action"] == "org.created"
    assert first["actor_role"] == "platform_operator"
    assert client.get("/api/audit/verify",
                      headers=two_fleets["a"]).json()["ok"]


def test_each_company_has_its_own_log(client, two_fleets):
    add(client, two_fleets["a"])
    b_log = client.get("/api/audit", headers=two_fleets["b"]).json()
    assert all(e["org_id"] == two_fleets["b_org"] for e in b_log["entries"])
    assert not any(e["action"] == "unit.created" for e in b_log["entries"])


def test_retire_keeps_the_unit(client, two_fleets):
    a = two_fleets["a"]
    uid = add(client, a).json()["unit"]["asset_id"]
    r = client.post(f"/api/assets/{uid}/retire", headers=a,
                    json={"reason": "Sold"})
    assert r.status_code == 200
    assert client.get("/api/assets", headers=a).json()["units"] == []
    gone = client.get("/api/assets?status=retired", headers=a).json()["units"]
    assert gone[0]["retired_reason"] == "Sold"


CSV = b"""Unit,Type,VIN,Year,Make
101,Tractor,1M8GDM9AXKP042788,2019,Freightliner
T1,Trailer,,2015,Utility
"""


def test_import_check_then_load(client, two_fleets):
    a = two_fleets["a"]
    files = {"file": ("fleet.csv", CSV, "text/csv")}
    r = client.post("/api/assets/import", headers=a, files=files)
    assert r.json()["ok"] and r.json()["saved"] == 0
    assert client.get("/api/assets", headers=a).json()["units"] == []
    r = client.post("/api/assets/import?commit=true", headers=a, files=files)
    assert r.json()["saved"] == 2
    assert len(client.get("/api/assets", headers=a).json()["units"]) == 2
    # Loading the same file again finds the duplicates and saves nothing.
    r = client.post("/api/assets/import?commit=true", headers=a, files=files)
    assert not r.json()["ok"] and r.json()["saved"] == 0


def test_import_with_a_bad_row_saves_nothing(client, two_fleets):
    a = two_fleets["a"]
    bad = CSV + b"T2,Spaceship,,,\n"
    r = client.post("/api/assets/import?commit=true", headers=a,
                    files={"file": ("f.csv", bad, "text/csv")})
    assert not r.json()["ok"] and r.json()["saved"] == 0
    assert client.get("/api/assets", headers=a).json()["units"] == []


def test_imports_stay_in_their_company(client, two_fleets):
    client.post("/api/assets/import?commit=true", headers=two_fleets["a"],
                files={"file": ("f.csv", CSV, "text/csv")})
    assert client.get("/api/assets",
                      headers=two_fleets["b"]).json()["units"] == []


# --- Every company collection, checked for leaks ----------------------------

@pytest.mark.parametrize("collection", sorted(COMPANY_COLLECTIONS))
def test_every_company_collection_is_walled(client, collection):
    a = CompanyData(Person("ua", "org_a", Role.ADMIN))
    b = CompanyData(Person("ub", "org_b", Role.ADMIN))

    async def go():
        await a.insert(collection, {"probe": "secret", "org_id": "org_b"})
        assert await b.find(collection, {"probe": "secret"}) == []
        assert await b.find_one(collection, {"probe": "secret"}) is None
        assert await b.count(collection, {"probe": "secret"}) == 0
        assert not await b.update(collection, {"probe": "secret"},
                                  {"probe": "stolen"})
        mine = await a.find(collection, {"probe": "secret"})
        # The company comes from the login, not from what was sent.
        assert mine[0]["org_id"] == "org_a"
    asyncio.run(go())


def test_no_route_bypasses_the_company_wall():
    """
    Company collections are reached only through CompanyData. Direct database
    use is allowed only for the global collections (companies and sign-ins)
    and for creating indexes.
    """
    src_dir = Path(__file__).resolve().parent.parent / "dtr"
    bad = []
    for f in src_dir.rglob("*.py"):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            for name in re.findall(r"\bdb\(\)\.(\w+)", line):
                if name in SHARED_COLLECTIONS:
                    continue
                if f.name == "db.py" and "create_index" in line:
                    continue
                bad.append(f"{f.name}:{n} {line.strip()}")
            if re.search(r"\bdb\(\)\[", line) and f.name != "db.py":
                bad.append(f"{f.name}:{n} {line.strip()}")
    assert bad == []
