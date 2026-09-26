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
    assert final["stop_reason"] == "confirmed by 2+ sources"

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
