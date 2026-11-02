"""Work orders: the full job from open to closed, and everything that must be refused."""
import pytest

from conftest import login

TRUCK = {"asset_type": "power_unit", "unit_number": "101",
         "vin": "1M8GDM9AXKP042788", "make": "Freightliner",
         "model_year": 2019}


def person(client, admin, name, role, email):
    r = client.post("/api/users", headers=admin, json={
        "name": name, "email": email, "role": role,
        "password": "password-123"})
    assert r.status_code == 201, r.text
    return r.json()["user_id"], login(client, email, "password-123")


@pytest.fixture
def shop(client, two_fleets):
    a = two_fleets["a"]
    unit = client.post("/api/assets", headers=a, json=TRUCK).json()["unit"]
    joe_id, joe = person(client, a, "Joe Tech", "mechanic",
                         "joe@a.example.com")
    ana_id, ana = person(client, a, "Ana Tech", "mechanic",
                         "ana@a.example.com")
    sam_id, sam = person(client, a, "Sam Lead", "shop_manager",
                         "sam@a.example.com")
    fm_id, fm = person(client, a, "Fran Fleet", "fleet_manager",
                       "fran@a.example.com")
    return {**two_fleets, "unit": unit, "joe": joe, "joe_id": joe_id,
            "ana": ana, "ana_id": ana_id, "sam": sam, "sam_id": sam_id,
            "fm": fm}


def new_job(client, h, unit, **kw):
    body = {"asset_id": unit["asset_id"], "complaint": "Left brake light out",
            "priority": "high", "category": "lighting", **kw}
    r = client.post("/api/workorders", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def post(client, h, wo, action, body=None, files=None, data=None):
    url = f"/api/workorders/{wo['work_order_id']}/{action}"
    if files:
        return client.post(url, headers=h, files=files, data=data or {})
    return client.post(url, headers=h, json=body or {})


def test_full_job_open_to_closed(client, shop):
    c, joe, sam = client, shop["joe"], shop["sam"]
    wo = new_job(c, shop["fm"], shop["unit"])     # fleet manager reports it
    assert wo["number"] == 1 and wo["status"] == "open"
    assert wo["unit_number"] == "101"

    r = post(c, sam, wo, "assign", {"user_ids": [shop["joe_id"]]})
    assert r.json()["assigned"][0]["name"] == "Joe Tech"
    assert post(c, joe, wo, "status", {"status": "in_progress"}
                ).json()["status"] == "in_progress"
    post(c, joe, wo, "status", {"status": "waiting_parts"})
    post(c, joe, wo, "status", {"status": "in_progress"})

    r = post(c, joe, wo, "labor", {"hours": 1.5, "note": "Diag + repair"})
    assert r.status_code == 200, r.text
    post(c, joe, wo, "parts", {"part_number": "LMP-1157",
                               "description": "Bulb", "qty": 2,
                               "unit_cost": 3.25})
    post(c, joe, wo, "vendor", {"vendor": "Bob's Electric", "amount": 40,
                                "invoice_number": "INV-9"})
    r = c.patch(f"/api/workorders/{wo['work_order_id']}", headers=joe,
                json={"cause": "Corroded socket",
                      "correction": "Cleaned socket, replaced bulb"})
    assert r.status_code == 200
    t = r.json()["totals"]
    assert t == {"labor_hours": 1.5, "parts_cost": 6.5, "vendor_cost": 40,
                 "cost_without_labor": 46.5}

    r = post(c, joe, wo, "complete", {"typed_name": "joe  tech"})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "complete"
    assert done["signoff"]["name"] == "Joe Tech"
    assert "complete as described" in done["signoff"]["statement"]

    r = post(c, sam, wo, "close")
    assert r.json()["status"] == "closed"
    assert [h["to"] for h in r.json()["history"]] == [
        "open", "in_progress", "waiting_parts", "in_progress", "complete",
        "closed"]
    assert c.get("/api/audit/verify", headers=shop["a"]).json()["ok"]


def test_numbers_run_per_company(client, shop):
    assert new_job(client, shop["a"], shop["unit"])["number"] == 1
    assert new_job(client, shop["a"], shop["unit"])["number"] == 2
    b_unit = client.post("/api/assets", headers=shop["b"],
                         json=TRUCK).json()["unit"]
    assert new_job(client, shop["b"], b_unit)["number"] == 1


def test_other_company_cannot_touch_job(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    b = shop["b"]
    assert client.get(f"/api/workorders/{wo['work_order_id']}",
                      headers=b).status_code == 404
    assert client.get("/api/workorders", headers=b).json()[
        "work_orders"] == []
    for action, body in [("labor", {"hours": 1}), ("notes", {"text": "x"}),
                         ("status", {"status": "in_progress"}),
                         ("cancel", {"reason": "x"})]:
        assert post(client, b, wo, action, body).status_code in (403, 404)


def test_cannot_open_job_on_other_companys_unit(client, shop):
    r = client.post("/api/workorders", headers=shop["b"], json={
        "asset_id": shop["unit"]["asset_id"], "complaint": "x"})
    assert r.status_code == 400


def test_signoff_needs_typed_name_matching(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"], correction="Fixed")
    post(client, shop["joe"], wo, "labor", {"hours": 1})
    for typed in ("", "Joe", "Ana Tech"):
        r = post(client, shop["joe"], wo, "complete", {"typed_name": typed})
        assert r.status_code == 400
    assert client.get(f"/api/workorders/{wo['work_order_id']}",
                      headers=shop["joe"]).json()["status"] == "open"


def test_signoff_needs_correction(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    post(client, shop["joe"], wo, "labor", {"hours": 1})
    r = post(client, shop["joe"], wo, "complete", {"typed_name": "Joe Tech"})
    assert r.status_code == 400


def test_tech_who_didnt_work_job_cannot_sign(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"], correction="Fixed")
    post(client, shop["joe"], wo, "labor", {"hours": 1})
    r = post(client, shop["ana"], wo, "complete", {"typed_name": "Ana Tech"})
    assert r.status_code == 400


def test_fleet_manager_cannot_sign_or_log_labor(client, shop):
    wo = new_job(client, shop["fm"], shop["unit"], correction="Fixed")
    assert post(client, shop["fm"], wo, "labor",
                {"hours": 1}).status_code == 403
    assert post(client, shop["fm"], wo, "complete",
                {"typed_name": "Fran Fleet"}).status_code == 400
    assert post(client, shop["fm"], wo, "notes",
                {"text": "Driver says it flickers"}).status_code == 200


def test_tech_logs_only_own_hours_lead_logs_anyones(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    r = post(client, shop["joe"], wo, "labor",
             {"hours": 1, "user_id": shop["ana_id"]})
    assert r.status_code == 403
    r = post(client, shop["sam"], wo, "labor",
             {"hours": 2, "user_id": shop["ana_id"]})
    assert r.json()["labor"][0]["name"] == "Ana Tech"


def test_labor_limits(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    for h in (0, -1, 25, "abc", None):
        assert post(client, shop["joe"], wo, "labor",
                    {"hours": h}).status_code == 400
    assert post(client, shop["joe"], wo, "labor",
                {"hours": 1, "date": "2099-01-01"}).status_code == 400


def test_mechanic_cannot_assign_close_or_cancel(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    assert post(client, shop["joe"], wo, "assign",
                {"user_ids": [shop["joe_id"]]}).status_code == 403
    assert post(client, shop["joe"], wo, "cancel",
                {"reason": "dup"}).status_code == 403


def test_signed_job_is_locked_and_corrected_by_amendment(client, shop):
    c, joe, sam = client, shop["joe"], shop["sam"]
    wo = new_job(c, joe, shop["unit"], correction="Replaced bulb")
    post(c, joe, wo, "labor", {"hours": 1})
    post(c, joe, wo, "complete", {"typed_name": "Joe Tech"})
    url = f"/api/workorders/{wo['work_order_id']}"

    # No silent edits after sign-off.
    assert c.patch(url, headers=joe, json={"correction": "x"}
                   ).status_code == 400
    # Adding a line needs a reason, and is marked as added afterwards.
    assert post(c, joe, wo, "parts", {"description": "Socket", "qty": 1}
                ).status_code == 400
    r = post(c, joe, wo, "parts", {"description": "Socket", "qty": 1,
                                   "reason": "Forgot to log it"})
    assert r.json()["parts"][0]["amended"] is True

    # Another tech can't amend; the signer and the shop lead can.
    assert post(c, shop["ana"], wo, "amend", {
        "field": "correction", "value": "y", "reason": "z"}).status_code == 403
    assert post(c, sam, wo, "amend", {
        "field": "correction", "value": "y"}).status_code == 400  # no reason
    r = post(c, sam, wo, "amend", {
        "field": "correction", "value": "Replaced bulb and socket",
        "reason": "Socket was replaced too"})
    assert r.status_code == 200
    a = r.json()["amendments"][0]
    assert a["before"] == "Replaced bulb"
    assert a["after"] == "Replaced bulb and socket"
    assert r.json()["correction"] == "Replaced bulb and socket"
    # The signature is untouched.
    assert r.json()["signoff"]["name"] == "Joe Tech"


def test_void_keeps_the_line(client, shop):
    c, joe = client, shop["joe"]
    wo = new_job(c, joe, shop["unit"])
    line = post(c, joe, wo, "labor", {"hours": 3}).json()["labor"][0]
    assert post(c, joe, wo, "void", {"kind": "labor",
                                     "line_id": line["line_id"],
                                     "reason": ""}).status_code == 400
    # Another tech can't void Joe's line.
    assert post(c, shop["ana"], wo, "void", {
        "kind": "labor", "line_id": line["line_id"],
        "reason": "x"}).status_code == 403
    r = post(c, joe, wo, "void", {"kind": "labor",
                                  "line_id": line["line_id"],
                                  "reason": "Wrong job"})
    got = r.json()
    assert got["labor"][0]["voided"] is True
    assert got["labor"][0]["void_reason"] == "Wrong job"
    assert got["totals"]["labor_hours"] == 0


def test_bad_status_moves_refused(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    for s in ("complete", "closed", "cancelled", "nonsense"):
        assert post(client, shop["joe"], wo, "status",
                    {"status": s}).status_code == 400


def test_close_needs_signoff_and_cancel_needs_reason(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    assert post(client, shop["sam"], wo, "close").status_code == 400
    assert post(client, shop["sam"], wo, "cancel",
                {"reason": " "}).status_code == 400
    r = post(client, shop["sam"], wo, "cancel", {"reason": "Duplicate"})
    assert r.json()["status"] == "cancelled"
    assert post(client, shop["joe"], wo, "labor",
                {"hours": 1}).status_code == 400


def test_job_list_views(client, shop):
    a = new_job(client, shop["joe"], shop["unit"], priority="low")
    b = new_job(client, shop["sam"], shop["unit"], priority="urgent")
    post(client, shop["sam"], a, "assign", {"user_ids": [shop["joe_id"]]})
    rows = client.get("/api/workorders", headers=shop["sam"]).json()[
        "work_orders"]
    assert [r["number"] for r in rows] == [b["number"], a["number"]]
    mine = client.get("/api/workorders?mine=true", headers=shop["joe"]
                      ).json()["work_orders"]
    assert [r["number"] for r in mine] == [a["number"]]


PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
       b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def test_photos_stay_in_company(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    r = post(client, shop["joe"], wo, "photos",
             files={"file": ("p.png", PNG, "image/png")},
             data={"caption": "Socket"})
    assert r.status_code == 200, r.text
    pid = r.json()["photos"][0]["photo_id"]
    url = f"/api/workorders/{wo['work_order_id']}/photos/{pid}"
    got = client.get(url, headers=shop["joe"])
    assert got.status_code == 200 and got.content == PNG
    assert client.get(url, headers=shop["b"]).status_code == 404
    bad = post(client, shop["joe"], wo, "photos",
               files={"file": ("x.txt", b"hello", "text/plain")})
    assert bad.status_code == 400


def test_errors_come_back_in_the_readers_language(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"])
    h = {**shop["sam"], "X-Lang": "en"}
    r = post(client, h, wo, "close")
    assert r.json()["detail"] == "Only a signed-off job can be closed."


def test_signoff_statement_saved_in_signers_language(client, shop):
    wo = new_job(client, shop["joe"], shop["unit"], correction="Fixed")
    post(client, shop["joe"], wo, "labor", {"hours": 1})
    h = {**shop["joe"], "X-Lang": "es"}
    r = post(client, h, wo, "complete", {"typed_name": "Joe Tech"})
    so = r.json()["signoff"]
    assert so["statement_lang"] == "es"
    from dtr.i18n import catalog
    if catalog("es").get("wo.signoff.statement"):
        assert so["statement"] == catalog("es")["wo.signoff.statement"]
