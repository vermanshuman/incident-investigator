import os
import tempfile
import time

import pytest

DB = os.path.join(tempfile.mkdtemp(), "test_api.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB.replace(os.sep, '/')}"

from fastapi.testclient import TestClient

from app.core.db import Base, SessionLocal, engine
from app.main import app
from app.models import Run, RunStatus


@pytest.fixture(autouse=True)
def fresh_db():
    """Each test starts from an empty database: state shared between tests
    hides real bugs and invents fake ones."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    """Signed in to the demo org as an approver - the common case."""
    with TestClient(app) as c:
        assert c.post("/auth/signin", json={"name": "Priya Nair"}).status_code == 200
        yield c


@pytest.fixture
def anonymous_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def owner_client():
    """Signed in as the owner of a fresh organization."""
    with TestClient(app) as c:
        r = c.post("/auth/signin", json={"name": "Rahul Mehta", "email": "rahul@example.com",
                                         "org_name": "Acme Shop"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "owner"
        yield c


@pytest.fixture
def incident(client):
    r = client.post("/incidents", json={"title": "500s on checkout",
                                        "description": "Error rate jumped a few minutes ago"})
    assert r.status_code == 201, r.text
    return r.json()


# --- a stand-in agent, so no test needs an LLM or the target app ------

EVENTS = [
    {"seq": 1, "node": "intake", "note": "Parsed incident"},
    {"seq": 2, "node": "triage", "note": "Triage: 500s on POST /checkout"},
    {"seq": 3, "node": "generate_hypotheses", "note": "3 hypotheses",
     "hypotheses": [
         {"id": "H1", "statement": "bad deploy", "category": "bad_deploy", "status": "open",
          "confidence": 0.3, "evidence_for": [], "evidence_against": []},
         {"id": "H2", "statement": "pool exhausted", "category": "resource_config", "status": "open",
          "confidence": 0.3, "evidence_for": [], "evidence_against": []},
     ]},
    {"seq": 4, "node": "run_tool", "note": "get_deploy_events: what shipped",
     "tool_call": {"step": 1, "tool": "get_deploy_events", "args": {}, "tests_hypothesis": "H1",
                   "why": "what shipped", "summary": "- [deploy:ab12] Remove validation",
                   "refs": ["deploy:ab12"], "latency_ms": 12.0, "error": None}},
    {"seq": 5, "node": "decide", "note": "deploy found",
     "hypotheses": [
         {"id": "H1", "statement": "bad deploy", "category": "bad_deploy", "status": "confirmed",
          "confidence": 0.9,
          "evidence_for": [{"tool": "get_deploy_events", "source_ref": "deploy:ab12", "excerpt": "x"}],
          "evidence_against": []},
         {"id": "H2", "statement": "pool exhausted", "category": "resource_config", "status": "refuted",
          "confidence": 0.1, "evidence_for": [], "evidence_against": []},
     ],
     "usage": {"calls": 4, "input_tokens": 3000, "output_tokens": 900, "cost_usd": 0.012}},
    {"seq": 6, "node": "write_report", "note": "Report ready",
     "report": {"summary": "s", "customer_impact": "c", "timeline": ["14:02 first error"],
                "root_cause": "Commit ab12 removed the null check", "confidence": "high",
                "supporting_evidence": [{"tool": "get_deploy_events", "source_ref": "deploy:ab12",
                                         "excerpt": "Remove validation"}],
                "ruled_out": ["H2: pool - no pool errors"],
                "fix": {"summary": "restore the check", "change": "+ if addr is None: 400",
                        "rollback": "revert ab12"},
                "unchecked_areas": ["metrics"], "is_external": False}},
]


@pytest.fixture
def fake_agent(monkeypatch):
    def investigate(title, description, on_event=None, thread_id=None, checkpointer=None):
        for event in EVENTS:
            on_event(dict(event))
        return {"step": 1, "stop_reason": "confirmed by symptom + change evidence"}

    monkeypatch.setattr("app.services.runs.investigate", investigate)


# --- waiting on background work --------------------------------------

def _await(run_id: str, states: set[RunStatus], what: str, timeout: float = 10.0) -> Run:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if run is not None and run.status in states:
                db.expunge(run)
                return run
        time.sleep(0.05)
    raise AssertionError(f"{what} did not happen within {timeout}s")


def _await_run(run_id: str, timeout: float = 10.0) -> Run:
    """Wait for the run to reach the approval gate (or fail)."""
    return _await(run_id, {RunStatus.awaiting_approval, RunStatus.failed}, "run", timeout)


def _await_terminal(run_id: str, timeout: float = 10.0) -> Run:
    """Wait for an approval decision to settle."""
    return _await(run_id, {RunStatus.completed, RunStatus.rejected, RunStatus.failed},
                  "decision", timeout)
