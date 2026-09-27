def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_incident_is_scoped_to_an_org(client, incident):
    from app.core.db import SessionLocal
    from app.models import Incident

    with SessionLocal() as db:
        row = db.get(Incident, incident["id"])
        assert row.org_id  # every tenant-owned row carries an org from the start


def test_listing_returns_the_incident(client, incident):
    ids = [i["id"] for i in client.get("/incidents").json()]
    assert incident["id"] in ids


def test_unknown_incident_is_404(client):
    assert client.get("/incidents/nope").status_code == 404
    assert client.post("/incidents/nope/investigate").status_code == 404


def test_dashboard_reports_usage_against_limits(client, incident):
    stats = client.get("/dashboard").json()
    assert stats["open_incidents"] >= 1
    assert stats["usage"]["run_limit"] > 0
    assert stats["plan"] == "free"
