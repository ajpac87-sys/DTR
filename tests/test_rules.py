"""The rules that need no server: company walls, units, CSV, change log."""
import copy

import pytest

from dtr import audit
from dtr.i18n import tr
from dtr.assets import csv_import, units
from dtr.tenancy import (DENY_ALL, Principal, Role, can_grant, scope_filter,
                         scoped)

A = Principal("u1", "org_a", Role.ADMIN)
OPS = Principal("ops", None, Role.PLATFORM_OPERATOR)


# --- Company walls ----------------------------------------------------------

def test_no_principal_sees_nothing():
    assert scope_filter(None) == DENY_ALL
    assert scoped(None, {"unit_number_key": "101"}) == DENY_ALL


def test_customer_sees_own_company_only():
    assert scope_filter(A) == {"org_id": "org_a"}


def test_a_condition_can_only_narrow():
    q = scoped(A, {"org_id": "org_b"})
    assert q == {"$and": [{"org_id": "org_a"}, {"org_id": "org_b"}]}


def test_operator_sees_all_companies():
    assert scope_filter(OPS) == {}


@pytest.mark.parametrize("role", [r for r in Role
                                  if r is not Role.PLATFORM_OPERATOR])
def test_customer_role_needs_a_company(role):
    with pytest.raises(ValueError):
        Principal("u", None, role)


def test_operator_cannot_have_a_home_company():
    with pytest.raises(ValueError):
        Principal("u", "org_a", Role.PLATFORM_OPERATOR)


def test_nobody_grants_above_themselves():
    assert not can_grant(Role.MECHANIC, Role.MECHANIC)
    assert not can_grant(Role.SHOP_MANAGER, Role.ADMIN)
    assert not can_grant(Role.SHOP_MANAGER, Role.FLEET_MANAGER)
    assert not can_grant(Role.FLEET_MANAGER, Role.ADMIN)
    assert not can_grant(Role.ADMIN, Role.PLATFORM_OPERATOR)
    assert can_grant(Role.SHOP_MANAGER, Role.MECHANIC)
    assert can_grant(Role.ADMIN, Role.SHOP_MANAGER)


# --- Units ------------------------------------------------------------------

GOOD_VIN = "1M8GDM9AXKP042788"     # standard check-digit example


def test_vin_good():
    assert units.check_vin(GOOD_VIN) == (GOOD_VIN, [], [])
    assert units.check_vin("1m8g-dm9a xkp042788")[0] == GOOD_VIN


def test_vin_bad_letters_refused():
    v, errors, _ = units.check_vin("1M8GDM9AXKP04278O")
    assert v is None and errors


def test_vin_wrong_check_digit_only_warns():
    v, errors, warnings = units.check_vin("1M8GDM9A1KP042788")
    assert v and not errors and warnings


def test_vin_short_warns_for_old_units():
    v, errors, warnings = units.check_vin("ABC12345")
    assert v == "ABC12345" and not errors and warnings


@pytest.mark.parametrize("word,kind", [
    ("Tractor", units.POWER_UNIT), ("truck", units.POWER_UNIT),
    ("Reefer", units.TRAILER), ("53' dry van", None), ("dry van",
                                                         units.TRAILER)])
def test_type_words(word, kind):
    assert units.parse_type(word) == kind


def test_unit_needs_type_and_number():
    _, errors, _ = units.build_unit({})
    assert len(errors) == 2


def test_furnished_unit_needs_owner_name():
    _, errors, _ = units.build_unit({"asset_type": "trailer",
                                     "unit_number": "T1",
                                     "owned_by_carrier": False})
    assert any("furnishes" in e for e in tr(errors))
    u, errors, _ = units.build_unit({"asset_type": "trailer",
                                     "unit_number": "T1",
                                     "furnished_by": "Penske"})
    assert not errors and u["owned_by_carrier"] is False


def test_unit_number_spacing_and_case_match():
    assert units.unit_key(" t 101 ") == units.unit_key("T  101")


# --- CSV import -------------------------------------------------------------

def _csv(text):
    return text.strip().encode()


def test_csv_loose_headings():
    r = csv_import.check_file(_csv(f"""
Unit #,Type,VIN,Year,Make,License Plate,State,Miles,Color
101,Tractor,{GOOD_VIN},2019,Freightliner,ABC123,ca,"412,000",Red
T-7,Reefer,,2015,Utility,,,,White
"""), set())
    assert r["ok"], r
    assert r["count"] == 2 and r["power_units"] == 1 and r["trailers"] == 1
    assert r["ignored_columns"] == ["Color"]
    u = r["units"][0]
    assert u["odometer"] == 412000 and u["plate_state"] == "CA"


def test_csv_all_or_nothing():
    r = csv_import.check_file(_csv("""
Unit,Type
101,truck
102,spaceship
"""), set())
    assert not r["ok"] and r["units"] == []
    assert r["rows"][1]["errors"]


def test_csv_duplicates_in_file_and_already_loaded():
    r = csv_import.check_file(_csv("""
Unit,Type
101,truck
101 ,truck
200,trailer
"""), {"200"})
    assert not r["ok"]
    errs = [e for row in tr(r["rows"]) for e in row["errors"]]
    assert any("also on row 2" in e for e in errs)
    assert any("already in DTR" in e for e in errs)


def test_csv_missing_columns_explained():
    r = csv_import.check_file(_csv("VIN,Make\nX,Y"), set())
    assert not r["ok"] and len(r["problems"]) == 2


def test_csv_excel_bom_and_semicolons():
    raw = "﻿Unit;Type\n5;trailer\n".encode("utf-8")
    assert csv_import.check_file(raw, set())["ok"]


# --- Change log -------------------------------------------------------------

def _chain(n):
    prev, out = audit.GENESIS, []
    for i in range(1, n + 1):
        e = {"org_id": "o", "seq": i, "at": "t", "actor_user_id": "u",
             "actor_name": "n", "actor_role": "admin", "action": "x",
             "record_type": "asset", "record_id": str(i), "before": None,
             "after": {"v": i}, "prev_hash": prev}
        e["hash"] = audit.chain_hash(e)
        prev = e["hash"]
        out.append(e)
    return out


def test_chain_intact():
    assert audit.verify_chain(_chain(5))["ok"]


def test_chain_shows_an_edit():
    c = copy.deepcopy(_chain(5))
    c[2]["after"] = {"v": 999}
    r = audit.verify_chain(c)
    assert not r["ok"] and r["at_seq"] == 3


def test_chain_shows_a_deletion():
    c = _chain(5)
    del c[1]
    assert not audit.verify_chain(c)["ok"]


# --- Languages -----------------------------------------------------------------

def test_every_language_has_every_message_with_same_blanks():
    import json
    import re
    from pathlib import Path
    from dtr.i18n import LANGUAGES
    root = Path(__file__).resolve().parent.parent / "dtr" / "static" / "locales"
    en = json.loads((root / "en.json").read_text(encoding="utf-8"))
    blanks = lambda s: sorted(re.findall(r"\{(\w+)\}", s))
    for code in LANGUAGES:
        cat = json.loads((root / f"{code}.json").read_text(encoding="utf-8"))
        assert set(cat) == set(en), code
        for k, v in en.items():
            assert blanks(cat[k]) == blanks(v), (code, k)
            assert cat[k].strip(), (code, k)


def test_every_word_on_screen_is_in_the_catalog():
    """A key used in app.js but missing from en.json would show as raw code."""
    import json
    import re
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / "dtr" / "static"
    en = json.loads((static / "locales" / "en.json").read_text(encoding="utf-8"))
    js = (static / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r'\bt\("([a-z_]+\.[a-z_.]+)"', js))
    missing = sorted(k for k in used if k not in en and not k.endswith("."))
    assert missing == []
