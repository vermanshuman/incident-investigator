from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/health").json() == {"status": "ok"}
