import os
import tempfile

import pytest

DB = os.path.join(tempfile.mkdtemp(), "test_api.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB.replace(os.sep, '/')}"

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def incident(client):
    r = client.post("/incidents", json={"title": "500s on checkout",
                                        "description": "Error rate jumped a few minutes ago"})
    assert r.status_code == 201, r.text
    return r.json()
