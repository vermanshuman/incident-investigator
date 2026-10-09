"""The approval gate: the only write action, and what guards it."""

import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from agent import github, llm, tools
from agent.nodes import report_markdown
from agent.runner import SERDE, investigate, resume
from agent.schemas import (
    Citation,
    FixProposal,
    Hypothesis,
    HypothesisSet,
    HypothesisUpdate,
    Report,
    Step,
    ToolCall,
    Triage,
)


class Script:
    """One tool call, then a confirmed hypothesis and a report."""

    def __init__(self):
        self.n = 0

    def __call__(self, schema, system, user):
        if schema is Triage:
            return Triage(error_signature="500s on /checkout", affected_endpoints=["/checkout"],
                          started_at=None, severity="high")
        if schema is HypothesisSet:
            return HypothesisSet(hypotheses=[
                Hypothesis(id="a", statement="bad deploy", category="bad_deploy"),
                Hypothesis(id="b", statement="pool", category="resource_config"),
                Hypothesis(id="c", statement="provider", category="external"),
            ])
        if schema is Step:
            self.n += 1
            if self.n == 1:
                return Step(next_call=ToolCall(tool="get_deploy_events", args={},
                                               tests_hypothesis="H1", why="what shipped"), note="deploys")
            if self.n == 2:
                return Step(next_call=ToolCall(tool="search_logs", args={"level": "ERROR"},
                                               tests_hypothesis="H1", why="signature"), note="logs")
            return Step(
                updates=[HypothesisUpdate(id="H1", status="confirmed", confidence=0.9, evidence_for=[
                    Citation(tool="get_deploy_events", source_ref="deploy:ab12", excerpt="Remove validation"),
                    Citation(tool="search_logs", source_ref="log:9", excerpt="NoneType country"),
                ])],
                conclude=True, note="done",
            )
        return Report(summary="Checkout failing", customer_impact="30% of checkouts fail",
                      timeline=["14:02 first error"], root_cause="Commit ab12 removed the null check",
                      confidence="high",
                      supporting_evidence=[Citation(tool="search_logs", source_ref="log:9", excerpt="NoneType")],
                      ruled_out=["H2: pool - no pool errors"],
                      fix=FixProposal(summary="restore the check", change="+ if addr is None: 400",
                                      rollback="revert ab12"),
                      unchecked_areas=["metrics"], is_external=False)


RESULTS = {
    "get_deploy_events": tools.ToolResult("- [deploy:ab12] Remove validation", ["deploy:ab12"]),
    "search_logs": tools.ToolResult("- [log:9] AttributeError on country", ["log:9"]),
}


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setattr(llm, "FAKE_RESPONDER", Script())
    monkeypatch.setattr(tools, "run_tool", lambda name, args: (RESULTS[name], 1.0, None))
    from agent import nodes

    monkeypatch.setattr(nodes, "run_tool", tools.run_tool)


@pytest.fixture
def saver(tmp_path):
    """A checkpointer on disk, so a run can outlive the process that began it."""
    conns = []

    def open_saver():
        conn = sqlite3.connect(tmp_path / "checkpoints.sqlite", check_same_thread=False)
        conns.append(conn)
        s = SqliteSaver(conn)
        s.serde = SERDE
        s.setup()
        return s

    yield open_saver
    for c in conns:
        c.close()


@pytest.fixture
def captured_issues(monkeypatch):
    calls = []

    def fake_create(title, body, labels=None, dry_run=False):
        calls.append({"title": title, "body": body, "labels": labels})
        return {"url": "https://github.com/acme/shop/issues/7", "number": 7, "dry_run": False}

    monkeypatch.setattr(github, "create_issue", fake_create)
    return calls


def test_run_pauses_before_the_write_action(agent, saver, captured_issues):
    final = investigate("500s", "checkout failing", thread_id="r1", saver=saver())
    assert final["report"] is not None
    assert final.get("github_issue_url") is None
    assert captured_issues == []  # nothing was filed without a human


def test_rejecting_stops_without_filing(agent, saver, captured_issues):
    investigate("500s", "checkout failing", thread_id="r2", saver=saver())
    final = resume("r2", approved=False, saver=saver())
    assert final["approval"] == "rejected"
    assert final.get("github_issue_url") is None
    assert captured_issues == []


def test_approving_files_the_issue_with_the_evidence(agent, saver, captured_issues):
    investigate("POST /checkout returning 500s", "checkout failing", thread_id="r3", saver=saver())
    final = resume("r3", approved=True, saver=saver())

    assert final["github_issue_url"] == "https://github.com/acme/shop/issues/7"
    issue = captured_issues[0]
    assert issue["title"].startswith("[incident]")
    assert "log:9" in issue["body"]  # the citation survives into the issue
    assert "Ruled out" in issue["body"] and "Not checked" in issue["body"]
    assert "has not been tested" in issue["body"]  # the fix is marked unverified
    assert "external-cause" not in issue["labels"]


def test_a_reviewers_edits_are_what_gets_filed(agent, saver, captured_issues):
    investigate("500s", "checkout failing", thread_id="r4", saver=saver())
    resume("r4", approved=True, saver=saver(),
           report_overrides={"root_cause": "Reviewer rewrote this", "confidence": "medium"})
    assert "Reviewer rewrote this" in captured_issues[0]["body"]
    assert "Confidence: **medium**" in captured_issues[0]["body"]


def test_a_paused_run_survives_a_restart(agent, saver, captured_issues):
    """Approval can come hours later, from a process that did not run the agent."""
    investigate("500s", "checkout failing", thread_id="r5", saver=saver())
    # a *new* saver instance, as a restarted process would open
    final = resume("r5", approved=True, saver=saver())
    assert final["github_issue_url"].endswith("/7")


def test_resuming_an_unknown_run_is_an_error(saver):
    with pytest.raises(ValueError, match="no checkpoint"):
        resume("never-existed", approved=True, saver=saver())


def test_the_node_refuses_when_approval_is_missing(agent, saver, captured_issues):
    """Belt and braces: even if the gate were bypassed, the node checks."""
    from agent.nodes import create_github_issue

    out = create_github_issue({"approval": None, "report": object(), "incident_title": "x"})
    assert "Not approved" in out["last_note"]
    assert captured_issues == []


def test_issue_body_marks_an_external_cause(agent, saver):
    state = investigate("500s", "checkout failing", thread_id="r6", saver=saver())
    state["report"] = state["report"].model_copy(update={"is_external": True})
    assert "external to our code" in report_markdown(state)


def test_without_a_token_it_is_a_dry_run(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    result = github.create_issue("t", "b")
    assert result["dry_run"] is True and result["url"] is None


def test_a_bad_edit_is_rejected_not_silently_stored(agent, saver, captured_issues):
    investigate("500s", "checkout failing", thread_id="r7", saver=saver())
    with pytest.raises(Exception, match="confidence"):
        resume("r7", approved=True, saver=saver(), report_overrides={"confidence": "very-sure"})
    assert captured_issues == []
