"""End-to-end graph test with a scripted fake LLM and fake tools (no API, no DB)."""

import pytest

from agent import llm, tools
from agent.runner import investigate
from agent.schemas import (
    Citation,
    FixProposal,
    Hypothesis,
    HypothesisSet,
    HypothesisStatus,
    HypothesisUpdate,
    Report,
    Step,
    ToolCall,
    Triage,
)


class ScriptedLLM:
    """Plays the on-call engineer: checks deploys, then logs, then the diff, then concludes."""

    def __init__(self):
        self.n = 0

    def __call__(self, schema, system, user):
        assert "untrusted" in system  # prompt-injection notice is always present
        if schema is Triage:
            return Triage(error_signature="500s on POST /checkout", affected_endpoints=["/checkout"],
                          started_at=None, severity="high")
        if schema is HypothesisSet:
            return HypothesisSet(hypotheses=[
                Hypothesis(id="x", statement="DB pool exhausted", category="resource_config", status="confirmed"),
                Hypothesis(id="y", statement="Bad deploy broke checkout", category="bad_deploy"),
                Hypothesis(id="z", statement="Payment provider down", category="external"),
            ])
        if schema is Step:
            self.n += 1
            if self.n == 1:
                return Step(next_call=ToolCall(tool="get_deploy_events", args={}, tests_hypothesis="H2", why="what shipped"), note="checking deploys")
            if self.n == 2:
                return Step(
                    updates=[HypothesisUpdate(id="H2", status="open", confidence=0.6,
                                              evidence_for=[Citation(tool="get_deploy_events", source_ref="deploy:abc123", excerpt="deploy 10s before")])],
                    next_call=ToolCall(tool="search_logs", args={"level": "ERROR"}, tests_hypothesis="H2", why="error signature"),
                    note="deploy found",
                )
            if self.n == 3:
                return Step(
                    updates=[
                        HypothesisUpdate(id="H1", status="refuted", confidence=0.05,
                                         evidence_against=[Citation(tool="search_logs", source_ref="log:9", excerpt="no pool errors")]),
                        HypothesisUpdate(id="H2", status="confirmed", confidence=0.9,
                                         evidence_for=[Citation(tool="search_logs", source_ref="log:9", excerpt="NoneType country"),
                                                       Citation(tool="search_logs", source_ref="log:FAKE", excerpt="hallucinated")]),
                    ],
                    next_call=ToolCall(tool="get_commit_diff", args={"sha": "abc123"}, tests_hypothesis="H2", why="see the change"),
                    note="stack trace matches",
                )
            return Step(conclude=True, note="done")
        if schema is Report:
            return Report(summary="s", customer_impact="c", timeline=[], root_cause="Commit abc123 removed the null check",
                          confidence="high",
                          supporting_evidence=[Citation(tool="search_logs", source_ref="log:9", excerpt="e"),
                                               Citation(tool="get_commit_diff", source_ref="commit:abc123", excerpt="e"),
                                               Citation(tool="search_logs", source_ref="log:NOPE", excerpt="made up")],
                          ruled_out=["H1: pool - no pool errors"], fix=FixProposal(summary="restore check", change="", rollback="revert"),
                          unchecked_areas=[], is_external=False)
        raise AssertionError(schema)


FAKE_TOOLS = {
    "get_deploy_events": tools.ToolResult("- [deploy:abc123] 05:23:48 deploy by Rahul: Remove validation", ["deploy:abc123"]),
    "search_logs": tools.ToolResult("- [log:9] x17 AttributeError: 'NoneType' object has no attribute 'country'", ["log:9"]),
    "get_commit_diff": tools.ToolResult("[commit:abc123] -if body.shipping_address is None:", ["commit:abc123"]),
}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setattr(llm, "FAKE_RESPONDER", ScriptedLLM())
    monkeypatch.setattr(tools, "run_tool", lambda name, args: (FAKE_TOOLS[name], 1.0, None))
    from agent import nodes

    monkeypatch.setattr(nodes, "run_tool", tools.run_tool)


def test_full_investigation(fake):
    events = []
    final = investigate("500s on checkout", "Error rate jumped at 14:02", on_event=events.append)

    # stopping rule: H2 confirmed by 2 different tools (deploys + logs) -> stop before the diff
    assert [c["tool"] for c in final["tool_calls"]] == ["get_deploy_events", "search_logs"]
    # deploy event (change) + logs (symptom) = both sides, so it stops here
    assert final["stop_reason"] == "confirmed by symptom + change evidence"

    hyps = {h.id: h for h in final["hypotheses"]}
    assert hyps["H1"].status == HypothesisStatus.refuted
    assert hyps["H2"].status == HypothesisStatus.confirmed
    # hallucinated citation (log:FAKE) was dropped; real ones kept
    assert {c.source_ref for c in hyps["H2"].evidence_for} == {"deploy:abc123", "log:9"}
    # model-invented "confirmed" status at generation time was reset to open
    assert hyps["H3"].status == HypothesisStatus.open

    r = final["report"]
    assert {c.source_ref for c in r.supporting_evidence} == {"log:9"}  # commit diff never fetched -> dropped
    assert any("removed by validator" in u for u in r.unchecked_areas)
    assert final.get("github_issue_url") is None  # stopped at the approval gate
    assert final["usage"]["calls"] == 6  # triage + hypotheses + 3 decide + report
    assert [e["node"] for e in events][:4] == ["intake", "triage", "generate_hypotheses", "decide"]


class OneSidedLLM:
    """Confirms a hypothesis from two SYMPTOM sources and tries to stop early -
    exactly the pool-exhaustion failure. The loop must push it to check what
    changed before it is allowed to conclude."""

    def __init__(self):
        self.n = 0
        self.nudged = []

    def __call__(self, schema, system, user):
        if schema is Triage:
            return Triage(error_signature="timeouts on /checkout", affected_endpoints=["/checkout"],
                          started_at=None, severity="high")
        if schema is HypothesisSet:
            return HypothesisSet(hypotheses=[
                Hypothesis(id="a", statement="DB pool exhausted", category="resource_config"),
                Hypothesis(id="b", statement="bad deploy", category="bad_deploy"),
                Hypothesis(id="c", statement="provider slow", category="external"),
            ])
        if schema is Step:
            self.n += 1
            self.nudged.append("Before concluding:" in user)
            if self.n == 1:
                return Step(next_call=ToolCall(tool="search_logs", args={"level": "ERROR"},
                                               tests_hypothesis="H1", why="error signature"), note="logs")
            if self.n == 2:
                return Step(next_call=ToolCall(tool="get_metrics", args={"metric": "db_pool_usage"},
                                               tests_hypothesis="H1", why="pool saturation"), note="metrics")
            if self.n == 3:
                # two symptom sources, and it wants to stop: not good enough
                return Step(
                    updates=[HypothesisUpdate(id="H1", status="confirmed", confidence=0.9, evidence_for=[
                        Citation(tool="search_logs", source_ref="log:44", excerpt="QueuePool limit reached"),
                        Citation(tool="get_metrics", source_ref="metric:db_pool_usage:*", excerpt="1.0"),
                    ])],
                    conclude=True, note="pool exhausted, done",
                )
            return Step(
                updates=[HypothesisUpdate(id="H1", status="confirmed", confidence=0.95, evidence_for=[
                    Citation(tool="get_deploy_events", source_ref="deploy:cc11", excerpt="db_pool_size 10 -> 1"),
                ])],
                conclude=True, note="found the config deploy",
            )
        return Report(summary="s", customer_impact="c", timeline=[], root_cause="pool shrunk by config commit",
                      confidence="high", supporting_evidence=[], ruled_out=[],
                      fix=FixProposal(summary="restore pool size", change="", rollback="revert"),
                      unchecked_areas=[], is_external=False)


ONE_SIDED_TOOLS = {
    "search_logs": tools.ToolResult("- [log:44] QueuePool limit of size 1 overflow 0 reached", ["log:44"]),
    "get_metrics": tools.ToolResult("- [metric:db_pool_usage:*] baseline=0.33 latest=1.0", ["metric:db_pool_usage:*"]),
    "get_deploy_events": tools.ToolResult(
        "- [deploy:cc11] deploy: Reduce DB pool size and fail fast on pool wait", ["deploy:cc11"]),
}


def test_one_sided_confirmation_keeps_investigating(monkeypatch):
    llm_script = OneSidedLLM()
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setattr(llm, "FAKE_RESPONDER", llm_script)
    monkeypatch.setattr(tools, "run_tool", lambda name, args: (ONE_SIDED_TOOLS[name], 1.0, None))
    from agent import nodes

    monkeypatch.setattr(nodes, "run_tool", tools.run_tool)

    final = investigate("timeouts", "Checkout slow since a few minutes ago")

    # it did NOT stop after the two symptom tools: the loop forced the change check
    assert [c["tool"] for c in final["tool_calls"]] == ["search_logs", "get_metrics", "get_deploy_events"]
    assert final["tool_calls"][-1]["why"].startswith("corroboration rule")
    assert final["stop_reason"] == "confirmed by symptom + change evidence"
    assert llm_script.nudged[2] is False and llm_script.nudged[3] is True  # nudge sent once one-sided
    h1 = next(h for h in final["hypotheses"] if h.id == "H1")
    assert {c.source_ref for c in h1.evidence_for} == {"log:44", "metric:db_pool_usage:*", "deploy:cc11"}


class StopsEarlyLLM:
    """Stops after one look at the logs without confirming anything - so the
    corroboration rule never fires. The loop must still check what changed
    before any root cause is written."""

    def __init__(self):
        self.n = 0

    def __call__(self, schema, system, user):
        if schema is Triage:
            return Triage(error_signature="timeouts", affected_endpoints=["/checkout"],
                          started_at=None, severity="high")
        if schema is HypothesisSet:
            return HypothesisSet(hypotheses=[
                Hypothesis(id="a", statement="pool exhausted", category="resource_config"),
                Hypothesis(id="b", statement="bad deploy", category="bad_deploy"),
                Hypothesis(id="c", statement="external", category="external"),
            ])
        if schema is Step:
            self.n += 1
            if self.n == 1:
                return Step(next_call=ToolCall(tool="search_logs", args={}, tests_hypothesis="H1",
                                               why="signature"), note="logs")
            return Step(conclude=True, note="pool is exhausted, that's the answer")
        return Report(summary="s", customer_impact="c", timeline=[], root_cause="pool exhausted",
                      confidence="high", supporting_evidence=[], ruled_out=[],
                      fix=FixProposal(summary="raise pool", change="", rollback=""),
                      unchecked_areas=[], is_external=False)


def test_change_history_is_always_checked_before_concluding(monkeypatch):
    results = {
        "search_logs": tools.ToolResult("- [log:44] QueuePool limit reached", ["log:44"]),
        "get_deploy_events": tools.ToolResult("- [deploy:cc11] Reduce DB pool size", ["deploy:cc11"]),
    }
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setattr(llm, "FAKE_RESPONDER", StopsEarlyLLM())
    monkeypatch.setattr(tools, "run_tool", lambda name, args: (results[name], 1.0, None))
    from agent import nodes

    monkeypatch.setattr(nodes, "run_tool", tools.run_tool)

    final = investigate("timeouts", "Checkout slow")
    assert [c["tool"] for c in final["tool_calls"]] == ["search_logs", "get_deploy_events"]
    assert final["tool_calls"][-1]["why"].startswith("corroboration rule")
