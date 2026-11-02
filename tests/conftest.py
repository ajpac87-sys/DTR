import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-for-tests-only-0123456789abcdef")

OPERATOR = {"email": "ops@apex.example.com", "password": "operator-pass-1"}


@pytest.fixture
def client(monkeypatch):
    """A running DTR app on a fresh, empty in-memory database."""
    from fastapi.testclient import TestClient
    from mongomock_motor import AsyncMongoMockClient

    from dtr import db as dbmod
    from dtr.main import app

    dbmod.set_db(AsyncMongoMockClient()["dtr_test"])
    monkeypatch.setenv("OPERATOR_EMAIL", OPERATOR["email"])
    monkeypatch.setenv("OPERATOR_PASSWORD", OPERATOR["password"])
    with TestClient(app) as c:
        yield c
    dbmod.set_db(None)


def login(client, email, password):
    r = client.post("/api/auth/login",
                    json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def two_fleets(client):
    """Two customer companies, each with an admin, set up by Apex."""
    ops = login(client, **OPERATOR)
    out = {"ops": ops}
    for key, name in (("a", "Acme Freight"), ("b", "Rival Hauling")):
        email = f"admin@{key}.example.com"
        r = client.post("/api/operator/orgs", headers=ops, json={
            "company_name": name, "admin_name": f"Admin {key.upper()}",
            "admin_email": email, "admin_password": "admin-pass-1"})
        assert r.status_code == 201, r.text
        out[key] = login(client, email, "admin-pass-1")
        out[key + "_org"] = r.json()["org"]["org_id"]
    return out
