"""A full run through the API with a fake agent: no LLM, no target app.

Proves the pieces the live UI depends on: the run executes off the request
path, every event is persisted, the SSE stream delivers them (including a
backlog replay after reconnect), and the report is stored as markdown.
"""

import json
import time

import pytest

from app.core.db import SessionLocal
from app.models import Report, Run, RunEvent, RunStatus

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


def _await_run(run_id: str, timeout: float = 10.0) -> Run:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if run.status in {RunStatus.awaiting_approval, RunStatus.failed}:
                db.expunge(run)
                return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_investigate_runs_off_the_request_path_and_persists_everything(client, incident, fake_agent):
    started = client.post(f"/incidents/{incident['id']}/investigate")
    assert started.status_code == 202
    run_id = started.json()["id"]
    # the request returned before the agent finished
    assert started.json()["status"] in {"queued", "running"}

    run = _await_run(run_id)
    assert run.status == RunStatus.awaiting_approval
    assert run.stop_reason == "confirmed by symptom + change evidence"
    assert run.llm_calls == 4 and run.cost_usd == pytest.approx(0.012)
    assert run.token_count == 3900

    detail = client.get(f"/runs/{run_id}").json()
    assert [e["seq"] for e in detail["events"]] == [1, 2, 3, 4, 5, 6]
    assert {h["statement"]: h["status"] for h in detail["hypotheses"]} == {
        "bad deploy": "confirmed", "pool exhausted": "refuted"}
    assert detail["report"]["root_cause"].startswith("Commit ab12")

    with SessionLocal() as db:
        body = db.query(Report).filter(Report.run_id == run_id).one().body_markdown
    assert "## Root cause" in body and "deploy:ab12" in body and "## Not checked" in body


def test_stream_replays_stored_events_after_reconnect(client, incident, fake_agent):
    run_id = client.post(f"/incidents/{incident['id']}/investigate").json()["id"]
    _await_run(run_id)

    with client.stream("GET", f"/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        payloads = _collect(response)
    assert [p["seq"] for p in payloads] == [1, 2, 3, 4, 5, 6]

    # a client that already saw the first three asks only for the rest
    with client.stream("GET", f"/runs/{run_id}/stream?last_seq=3") as response:
        payloads = _collect(response)
    assert [p["seq"] for p in payloads] == [4, 5, 6]


def _collect(response) -> list[dict]:
    """Read an SSE response until the server signals the end of the run."""
    out, event = [], None
    for raw in response.iter_lines():
        line = raw.strip()
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and event == "run":
            out.append(json.loads(line.split(":", 1)[1].strip()))
        elif event == "end":
            break
    return out


def test_events_are_stored_with_a_type(client, incident, fake_agent):
    run_id = client.post(f"/incidents/{incident['id']}/investigate").json()["id"]
    _await_run(run_id)
    with SessionLocal() as db:
        types = {e.seq: e.type for e in db.query(RunEvent).filter(RunEvent.run_id == run_id)}
    assert types[4] == "tool_call" and types[6] == "report" and types[1] == "node"


def test_a_failing_agent_surfaces_the_error(client, incident, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("model exploded")

    monkeypatch.setattr("app.services.runs.investigate", boom)
    run_id = client.post(f"/incidents/{incident['id']}/investigate").json()["id"]
    run = _await_run(run_id)
    assert run.status == RunStatus.failed
    assert "model exploded" in run.error
