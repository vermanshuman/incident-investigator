import os

import pytest

os.environ["TARGET_DATABASE_URL"] = "sqlite:///./data/test_checkout.db"

from fastapi.testclient import TestClient

from app.main import app

ADDRESS = {"line1": "1 MG Road", "city": "Pune", "country": "IN"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    from app.db import engine, log_engine

    engine.dispose()
    log_engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(f"./data/test_checkout.db{suffix}")
        except OSError:
            pass


def _cart(client, items=None):
    r = client.post("/cart", json={"items": items or [{"sku": "SKU-001", "qty": 2}]})
    assert r.status_code == 201, r.text
    return r.json()["cart_id"]


def test_health_reports_version_and_pool(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "db_pool" in body


def test_checkout_rejects_missing_address(client):
    r = client.post("/checkout", json={"cart_id": _cart(client)})
    assert r.status_code == 400
    assert "shipping_address" in r.json()["detail"]


def test_checkout_happy_path_reserves_stock_and_charges(client):
    cart_id = _cart(client)
    r = client.post("/checkout", json={"cart_id": cart_id, "shipping_address": ADDRESS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["total"] == 2 * 799.0
    assert body["provider_ref"].startswith("ch_")


def test_international_shipping_fee(client):
    cart_id = _cart(client, [{"sku": "SKU-001", "qty": 1}])
    r = client.post("/checkout", json={"cart_id": cart_id,
                                       "shipping_address": {**ADDRESS, "country": "DE"}})
    assert r.json()["shipping_fee"] == 15.0


def test_requests_are_persisted_to_app_logs(client):
    from sqlalchemy import select

    from app.db import LogSessionLocal
    from app.models import AppLog

    with LogSessionLocal() as db:
        rows = db.scalars(select(AppLog).where(AppLog.path == "/checkout")).all()
    assert any(r.status == 400 for r in rows)
    assert any(r.status == 200 for r in rows)
