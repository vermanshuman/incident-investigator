"""A full run through the API with a fake agent: no LLM, no target app.

Proves the pieces the live UI depends on: the run executes off the request
path, every event is persisted, the SSE stream delivers them (including a
backlog replay after reconnect), and the report is stored as markdown.
"""

import json

import pytest

from app.core.db import SessionLocal
from app.models import Report, Run, RunEvent, RunStatus
from tests.conftest import _await_run, _await_terminal


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


# --- the approval gate -------------------------------------------------

def _paused_run(client, incident) -> str:
    run_id = client.post(f"/incidents/{incident['id']}/investigate").json()["id"]
    _await_run(run_id)
    return run_id


def test_approval_requires_a_signed_in_reviewer(client, incident, fake_agent):
    run_id = _paused_run(client, incident)
    client.post("/auth/signout")
    r = client.post(f"/runs/{run_id}/decision", json={"approved": True})
    assert r.status_code == 401

    with SessionLocal() as db:
        assert db.get(Run, run_id).status == RunStatus.awaiting_approval  # still gated


def test_approving_records_who_and_files_the_issue(client, incident, fake_agent, monkeypatch):
    filed = {}

    def fake_resume(thread_id, approved, report_overrides=None, on_event=None, start_seq=0, saver=None):
        filed["approved"] = approved
        filed["overrides"] = report_overrides
        if on_event:
            on_event({"seq": start_seq + 1, "node": "create_github_issue", "note": "Opened issue #7"})
        return {"github_issue_url": "https://github.com/acme/shop/issues/7"}

    monkeypatch.setattr("app.services.runs.resume", fake_resume)
    run_id = _paused_run(client, incident)

    assert client.post(f"/runs/{run_id}/decision", json={"approved": True}).status_code == 202
    run = _await_terminal(run_id)
    assert run.status == RunStatus.completed
    assert filed["approved"] is True

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["report"]["approved_by"] == "Priya Nair"
    assert detail["report"]["github_issue_url"].endswith("/7")

    audit = client.get(f"/runs/{run_id}/audit").json()
    actions = [(a["actor"], a["action"]) for a in audit]
    assert ("Priya Nair", "approved") in actions
    assert ("Priya Nair", "issue_created") in actions


def test_rejecting_files_nothing_but_is_recorded(client, incident, fake_agent, monkeypatch):
    calls = []

    def fake_resume(thread_id, approved, report_overrides=None, on_event=None, start_seq=0, saver=None):
        calls.append(approved)
        return {"approval": "rejected"}

    monkeypatch.setattr("app.services.runs.resume", fake_resume)
    run_id = _paused_run(client, incident)

    client.post(f"/runs/{run_id}/decision", json={"approved": False})
    run = _await_terminal(run_id)
    assert run.status == RunStatus.rejected
    assert calls == [False]

    audit = client.get(f"/runs/{run_id}/audit").json()
    assert [(a["actor"], a["action"]) for a in audit] == [("Priya Nair", "rejected")]
    assert client.get(f"/runs/{run_id}").json()["report"]["github_issue_url"] is None


def test_reviewer_edits_are_passed_through_and_recorded(client, incident, fake_agent, monkeypatch):
    seen = {}

    def fake_resume(thread_id, approved, report_overrides=None, on_event=None, start_seq=0, saver=None):
        seen["overrides"] = report_overrides
        return {"github_issue_url": "https://github.com/acme/shop/issues/8"}

    monkeypatch.setattr("app.services.runs.resume", fake_resume)
    run_id = _paused_run(client, incident)

    client.post(f"/runs/{run_id}/decision", json={
        "approved": True, "root_cause": "Reviewer rewrote this", "fix_summary": "revert it"})
    _await_terminal(run_id)

    assert seen["overrides"] == {"root_cause": "Reviewer rewrote this", "fix": {"summary": "revert it"}}
    audit = client.get(f"/runs/{run_id}/audit").json()
    edited = next(a for a in audit if a["action"] == "edited")
    assert edited["detail"]["fields"] == ["fix", "root_cause"]


def test_a_run_cannot_be_decided_twice(client, incident, fake_agent, monkeypatch):
    monkeypatch.setattr("app.services.runs.resume",
                        lambda *a, **kw: {"github_issue_url": None})
    run_id = _paused_run(client, incident)
    client.post(f"/runs/{run_id}/decision", json={"approved": True})
    _await_terminal(run_id)

    again = client.post(f"/runs/{run_id}/decision", json={"approved": True})
    assert again.status_code == 409



