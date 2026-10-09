"""Multi-tenancy, roles, plan limits, API keys and billing."""

import pytest

from app.core.db import SessionLocal
from app.core.plans import PLANS, usage_for
from app.models import Organization, Run, RunStatus

# --- isolation --------------------------------------------------------

def test_one_org_cannot_see_anothers_incidents(client, incident, owner_client):
    """The property that makes this safe to sell: data is scoped, not filtered
    by the UI."""
    mine = [i["id"] for i in client.get("/incidents").json()]
    theirs = [i["id"] for i in owner_client.get("/incidents").json()]
    assert incident["id"] in mine
    assert incident["id"] not in theirs

    # and a direct fetch by id is a 404, not someone else's data
    assert owner_client.get(f"/incidents/{incident['id']}").status_code == 404
    assert owner_client.post(f"/incidents/{incident['id']}/investigate").status_code == 404


def test_signing_in_with_an_org_name_creates_an_owned_org(owner_client):
    me = owner_client.get("/auth/me").json()
    assert me["org"]["name"] == "Acme Shop"
    assert me["role"] == "owner"
    assert me["org"]["slug"] == "acme-shop"


def test_a_user_can_belong_to_several_orgs_and_switch(owner_client):
    second = owner_client.post("/auth/signin", json={
        "name": "Rahul Mehta", "email": "rahul@example.com", "org_name": "Second Co"}).json()
    assert len(second["orgs"]) == 2

    first_id = next(o["id"] for o in second["orgs"] if o["name"] == "Acme Shop")
    switched = owner_client.post("/auth/switch-org", json={"org_id": first_id}).json()
    assert switched["org"]["name"] == "Acme Shop"


def test_cannot_switch_into_an_org_you_do_not_belong_to(client, owner_client):
    outsider_org = owner_client.get("/auth/me").json()["org"]["id"]
    assert client.post("/auth/switch-org", json={"org_id": outsider_org}).status_code == 404


# --- roles ------------------------------------------------------------

def test_a_viewer_can_read_but_not_investigate(owner_client, client):
    owner_client.post("/org/members", json={"name": "Lena Fischer", "email": "lena@example.com",
                                            "role": "viewer"})
    viewer = owner_client  # re-sign-in below switches identity
    viewer.post("/auth/signout")
    viewer.post("/auth/signin", json={"name": "Lena Fischer", "email": "lena@example.com"})

    # Lena signed in without an org name, so she lands in the demo org as approver;
    # her viewer membership is in Acme Shop, which she can switch to.
    orgs = viewer.get("/auth/me").json()["orgs"]
    acme = next(o for o in orgs if o["name"] == "Acme Shop")
    assert acme["role"] == "viewer"
    viewer.post("/auth/switch-org", json={"org_id": acme["id"]})

    assert viewer.get("/incidents").status_code == 200
    denied = viewer.post("/incidents", json={"title": "t", "description": "d"})
    assert denied.status_code == 403
    assert "approver" in denied.text


def test_only_an_owner_manages_members_and_plans(client):
    """The demo-org approver may investigate but not change the organization."""
    assert client.post("/org/members", json={"name": "X"}).status_code == 403
    assert client.post("/org/plan", json={"plan": "pro"}).status_code == 403
    assert client.post("/org/api-keys", json={"name": "k"}).status_code == 403


def test_an_org_must_keep_an_owner(owner_client):
    me = owner_client.get("/auth/me").json()
    r = owner_client.put(f"/org/members/{me['id']}", json={"role": "viewer"})
    assert r.status_code == 409


# --- plan limits ------------------------------------------------------

def _exhaust_runs(org_id: str, count: int) -> None:
    from datetime import UTC, datetime

    with SessionLocal() as db:
        for _ in range(count):
            db.add(Run(org_id=org_id, incident_id="x", status=RunStatus.completed,
                       started_at=datetime.now(UTC).replace(tzinfo=None), cost_usd=0.05))
        db.commit()


def test_investigating_is_blocked_once_the_plan_limit_is_reached(client, incident, fake_agent):
    org_id = client.get("/auth/me").json()["org"]["id"]
    with SessionLocal() as db:
        limit = db.get(Organization, org_id).monthly_run_limit
    _exhaust_runs(org_id, limit)

    blocked = client.post(f"/incidents/{incident['id']}/investigate")
    assert blocked.status_code == 402
    assert "Plan limit reached" in blocked.text


def test_a_replay_is_never_blocked_by_a_limit(client, incident, fake_agent):
    """Replays spend nothing, so the demo keeps working on an exhausted plan."""
    org_id = client.get("/auth/me").json()["org"]["id"]
    with SessionLocal() as db:
        limit = db.get(Organization, org_id).monthly_run_limit
    _exhaust_runs(org_id, limit)

    allowed = client.post(f"/incidents/{incident['id']}/investigate",
                          json={"replay": "cassettes/s01_null_check.jsonl"})
    assert allowed.status_code == 202
    assert allowed.json()["replayed"] is True


def test_usage_is_metered_for_the_current_period(client, incident, fake_agent):
    org_id = client.get("/auth/me").json()["org"]["id"]
    _exhaust_runs(org_id, 3)
    with SessionLocal() as db:
        usage = usage_for(db, db.get(Organization, org_id))
    assert usage.runs >= 3
    assert usage.cost_usd >= 0.15
    assert usage.period_start.day == 1


def test_org_endpoint_reports_usage_and_plans(client):
    body = client.get("/org").json()
    assert body["plan"] == "free"
    assert body["usage"]["run_limit"] == PLANS["free"].monthly_run_limit
    assert {p["key"] for p in body["plans"]} == {"free", "pro"}
    assert next(p for p in body["plans"] if p["current"])["key"] == "free"


# --- API keys ---------------------------------------------------------

@pytest.fixture
def api_key(owner_client) -> str:
    r = owner_client.post("/org/api-keys", json={"name": "Grafana alerts"})
    assert r.status_code == 201, r.text
    return r.json()["secret"]


def test_the_secret_is_shown_once_and_only_the_prefix_afterwards(owner_client, api_key):
    listed = owner_client.get("/org/api-keys").json()
    assert len(listed) == 1
    assert "secret" not in listed[0]
    assert api_key.startswith(listed[0]["prefix"])


def test_an_api_key_opens_incidents_for_its_own_org(anonymous_client, api_key, owner_client):
    r = anonymous_client.post("/v1/incidents", json={
        "title": "Checkout 500s", "description": "Alert fired", "investigate": False,
    }, headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 202, r.text
    created = r.json()["incident"]["id"]

    # it landed in the key's org, visible to that org only
    assert created in [i["id"] for i in owner_client.get("/incidents").json()]


def test_an_api_key_cannot_approve(anonymous_client, api_key, owner_client, fake_agent):
    started = anonymous_client.post("/v1/incidents", json={
        "title": "t", "description": "d", "investigate": True,
    }, headers={"Authorization": f"Bearer {api_key}"})
    run = started.json()["run"]
    assert run is not None

    from tests.test_run_stream import _await_run

    _await_run(run["id"])
    denied = anonymous_client.post(f"/runs/{run['id']}/decision", json={"approved": True},
                                   headers={"Authorization": f"Bearer {api_key}"})
    assert denied.status_code == 403
    assert "signed-in person" in denied.text


def test_a_revoked_key_stops_working(anonymous_client, owner_client, api_key):
    key_id = owner_client.get("/org/api-keys").json()[0]["id"]
    assert owner_client.delete(f"/org/api-keys/{key_id}").status_code == 204
    r = anonymous_client.get("/v1/ping", headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 401


def test_a_bogus_key_is_rejected(anonymous_client):
    assert anonymous_client.get("/v1/ping", headers={"Authorization": "Bearer iiv_nonsense"}).status_code == 401
    assert anonymous_client.get("/v1/ping").status_code == 401


def test_an_alert_is_recorded_even_when_the_plan_is_exhausted(anonymous_client, api_key, owner_client):
    org_id = owner_client.get("/auth/me").json()["org"]["id"]
    with SessionLocal() as db:
        limit = db.get(Organization, org_id).monthly_run_limit
    _exhaust_runs(org_id, limit)

    r = anonymous_client.post("/v1/incidents", json={"title": "t", "description": "d"},
                              headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 202
    assert r.json()["run"] is None
    assert "limit" in r.json()["note"].lower()
    assert r.json()["incident"]["id"]  # the alert was not lost


# --- billing ----------------------------------------------------------

def test_upgrading_without_stripe_is_simulated_but_real_in_effect(owner_client, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    r = owner_client.post("/org/plan", json={"plan": "pro"}).json()
    assert r["simulated"] is True and r["applied"] is True
    assert "No payment was taken" in r["message"]

    body = owner_client.get("/org").json()
    assert body["plan"] == "pro"
    assert body["usage"]["run_limit"] == PLANS["pro"].monthly_run_limit


def test_an_unknown_plan_is_rejected(owner_client):
    assert owner_client.post("/org/plan", json={"plan": "enterprise"}).status_code == 404


def test_stripe_webhook_applies_the_plan(anonymous_client, owner_client):
    org_id = owner_client.get("/auth/me").json()["org"]["id"]
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"customer": "cus_123", "subscription": "sub_123",
                            "client_reference_id": org_id,
                            "metadata": {"org_id": org_id, "plan": "pro"}}},
    }
    assert anonymous_client.post("/v1/stripe/webhook", json=event).json()["applied"] == "pro"
    assert owner_client.get("/org").json()["plan"] == "pro"


def test_a_webhook_with_a_bad_signature_is_refused(anonymous_client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    r = anonymous_client.post("/v1/stripe/webhook", json={"type": "checkout.session.completed"},
                              headers={"Stripe-Signature": "t=1,v1=wrong"})
    assert r.status_code == 400
