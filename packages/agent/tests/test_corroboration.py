"""A confirmation needs the symptom AND what changed - the s03 lesson."""

from agent.corroboration import (
    change_history_checked,
    change_history_empty,
    corroborated,
    missing_side,
    nudge,
    pending_confirmations,
)
from agent.schemas import Citation, Hypothesis, HypothesisStatus


def _hyp(tools, status=HypothesisStatus.confirmed):
    return Hypothesis(id="H1", statement="s", category="resource_config", status=status,
                      evidence_for=[Citation(tool=t, source_ref=f"{t}:1", excerpt="") for t in tools])


def _state(calls):
    return {"tool_calls": [{"tool": t, "refs": refs, "error": None} for t, refs in calls]}


def test_two_symptom_sources_are_not_enough():
    """The pool-exhaustion failure: a QueuePool log plus a pool metric look like
    two sources but never reach the config change that caused it."""
    h = _hyp(["search_logs", "get_metrics"])
    state = _state([("search_logs", ["log:44"]), ("get_metrics", ["metric:db_pool_usage:*"])])
    assert missing_side(h, state) == "change"
    assert corroborated(state, [h]) == []
    assert "what changed" in nudge(pending_confirmations(state, [h]), state)


def test_symptom_plus_change_is_corroborated():
    h = _hyp(["search_logs", "get_commit_diff"])
    state = _state([("search_logs", ["log:1"]), ("get_commit_diff", ["commit:ab"])])
    assert missing_side(h, state) is None
    assert len(corroborated(state, [h])) == 1


def test_change_evidence_alone_is_not_enough():
    h = _hyp(["get_deploy_events", "get_commit_diff"])
    state = _state([("get_deploy_events", ["deploy:1"]), ("get_commit_diff", ["commit:ab"])])
    assert missing_side(h, state) == "symptom"
    assert "symptom in production" in nudge(pending_confirmations(state, [h]), state)


def test_nothing_deployed_counts_as_change_evidence():
    """The external case must stay reachable: an empty deploy history IS evidence."""
    h = _hyp(["search_logs", "get_metrics"])
    state = _state([("search_logs", ["log:76"]), ("get_deploy_events", [])])
    assert change_history_empty(state)
    assert missing_side(h, state) is None
    assert len(corroborated(state, [h])) == 1


def test_unchecked_change_history_is_not_empty_history():
    state = _state([("search_logs", ["log:1"])])
    assert not change_history_checked(state)
    assert not change_history_empty(state)


def test_only_confirmed_hypotheses_are_judged():
    state = _state([("search_logs", ["log:1"])])
    open_h = _hyp(["search_logs"], status=HypothesisStatus.open)
    assert pending_confirmations(state, [open_h]) == []
    assert corroborated(state, [open_h]) == []
