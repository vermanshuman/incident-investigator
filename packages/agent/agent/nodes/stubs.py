"""Placeholder node implementations so the graph compiles and can be traced end to end."""

from agent.schemas import (
    Citation,
    Confidence,
    FixProposal,
    Hypothesis,
    HypothesisStatus,
    Report,
    Triage,
)
from agent.state import InvestigationState


def _tick(state: InvestigationState) -> dict:
    b = dict(state["budget"])
    b["steps"] += 1
    return {"budget": b}


def intake(state: InvestigationState) -> dict:
    return _tick(state)


def triage(state: InvestigationState) -> dict:
    return {
        **_tick(state),
        "triage": Triage(
            error_signature="stub",
            affected_endpoints=["POST /checkout"],
            time_window_start="",
            time_window_end="",
            severity="high",
        ),
    }


def generate_hypotheses(state: InvestigationState) -> dict:
    return {
        **_tick(state),
        "hypotheses": [
            Hypothesis(id="H1", statement="DB connection issue", category="resource_config"),
            Hypothesis(id="H2", statement="Bad deploy", category="bad_deploy"),
            Hypothesis(id="H3", statement="External provider outage", category="external"),
        ],
    }


def select_hypothesis(state: InvestigationState) -> dict:
    open_ = [h for h in state["hypotheses"] if h.status == HypothesisStatus.open]
    return {**_tick(state), "selected_hypothesis_id": open_[0].id if open_ else None}


def gather_evidence(state: InvestigationState) -> dict:
    return _tick(state)


def evaluate(state: InvestigationState) -> dict:
    hyps = []
    for h in state["hypotheses"]:
        if h.id == state.get("selected_hypothesis_id"):
            confirmed = h.id == "H2"
            h = h.model_copy(
                update={
                    "status": HypothesisStatus.confirmed if confirmed else HypothesisStatus.refuted,
                    "evidence_for": [
                        Citation(tool="search_logs", source_ref="stub", excerpt="stub"),
                        Citation(tool="get_commit_diff", source_ref="stub", excerpt="stub"),
                    ]
                    if confirmed
                    else [],
                }
            )
        hyps.append(h)
    return {**_tick(state), "hypotheses": hyps}


def propose_fix(state: InvestigationState) -> dict:
    return _tick(state)


def write_report(state: InvestigationState) -> dict:
    confirmed = next(
        (h for h in state["hypotheses"] if h.status == HypothesisStatus.confirmed), None
    )
    return {
        **_tick(state),
        "report": Report(
            summary="stub",
            customer_impact="stub",
            timeline=[],
            root_cause=confirmed.statement if confirmed else "unknown",
            confidence=Confidence.low,
            supporting_evidence=confirmed.evidence_for if confirmed else [],
            ruled_out=[
                h.statement for h in state["hypotheses"] if h.status == HypothesisStatus.refuted
            ],
            fix=FixProposal(summary="stub", diff_or_config_change="", rollback=""),
            unchecked_areas=["everything - stub run"],
            is_external=bool(confirmed and confirmed.category == "external"),
        ),
    }


def create_github_issue(state: InvestigationState) -> dict:
    return {**_tick(state), "github_issue_url": None}
