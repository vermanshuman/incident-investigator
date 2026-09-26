"""Graph nodes. Each takes InvestigationState and returns a partial update.

intake -> triage -> generate_hypotheses -> decide <-> run_tool -> write_report -> [approval] -> create_github_issue
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from agent import corroboration, prompts
from agent.guardrails import budget_exceeded, repeated_tool_call
from agent.llm import Call, call_structured
from agent.schemas import (
    Citation,
    Hypothesis,
    HypothesisSet,
    HypothesisStatus,
    Report,
    Step,
    Triage,
)
from agent.state import InvestigationState, ToolRecord
from agent.tools import run_tool


def _account(state: InvestigationState, call: Call) -> dict:
    u = dict(state.get("usage") or {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    u["calls"] += 1
    u["input_tokens"] += call.input_tokens
    u["output_tokens"] += call.output_tokens
    u["cost_usd"] = round(u["cost_usd"] + call.cost_usd, 6)
    return {"usage": u}


def intake(state: InvestigationState) -> dict:
    return {
        "step": 0,
        "tool_calls": [],
        "hypotheses": [],
        "pending_call": None,
        "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        "incident_created_at": state.get("incident_created_at") or datetime.now(UTC).isoformat(timespec="seconds"),
        "last_note": "Parsed incident",
    }


def triage(state: InvestigationState) -> dict:
    call = call_structured(
        Triage, prompts.SYSTEM,
        prompts.TRIAGE.format(title=state["incident_title"], description=state["incident_description"],
                              created_at=state["incident_created_at"]),
        small=True,
    )
    t: Triage = call.output
    return {**_account(state, call), "triage": t, "last_note": f"Triage: {t.error_signature}"}


def generate_hypotheses(state: InvestigationState) -> dict:
    call = call_structured(HypothesisSet, prompts.SYSTEM, prompts.HYPOTHESES.format(case=prompts.render_case(state)))
    hs: list[Hypothesis] = call.output.hypotheses
    for i, h in enumerate(hs, 1):  # normalise ids and reset any status the model invented
        h.id, h.status, h.evidence_for, h.evidence_against = f"H{i}", HypothesisStatus.open, [], []
    return {**_account(state, call), "hypotheses": hs, "last_note": f"{len(hs)} hypotheses"}


def _apply_updates(state: InvestigationState, step: Step) -> list[Hypothesis]:
    """Merge the model's updates, keeping only citations that reference real refs."""
    known = {r for c in state.get("tool_calls", []) for r in c["refs"]}
    by_id = {h.id: h for h in state["hypotheses"]}
    for u in step.updates:
        h = by_id.get(u.id)
        if not h:
            continue
        ok = lambda cs: [c for c in cs if c.source_ref in known]
        h.status, h.confidence = u.status, u.confidence
        h.evidence_for = _dedupe(h.evidence_for + ok(u.evidence_for))
        h.evidence_against = _dedupe(h.evidence_against + ok(u.evidence_against))
        if h.status == HypothesisStatus.confirmed and not h.evidence_for:
            h.status = HypothesisStatus.inconclusive  # confirmed without real evidence is not confirmed
    return list(by_id.values())


def _dedupe(cs: list[Citation]) -> list[Citation]:
    seen, out = set(), []
    for c in cs:
        if c.source_ref not in seen:
            seen.add(c.source_ref)
            out.append(c)
    return out


def decide(state: InvestigationState) -> dict:
    """Evaluate the last tool result and choose the next action, in ONE call."""
    u = state.get("usage") or {}
    reason = budget_exceeded(state["budget"], state["step"],
                             u.get("input_tokens", 0) + u.get("output_tokens", 0), u.get("cost_usd", 0.0))
    if reason:
        return {"pending_call": None, "stop_reason": reason, "last_note": f"Stopping: {reason}"}

    calls = state.get("tool_calls", [])
    case = prompts.render_case(state)
    steps_left = state["budget"]["max_steps"] - state["step"]
    if calls:
        last = calls[-1]
        user = prompts.STEP.format(case=case, step=last["step"], tool=last["tool"], hid=last["tests_hypothesis"],
                                   result=last["summary"], steps_left=steps_left)
    else:
        user = prompts.FIRST_STEP.format(case=case, steps_left=steps_left)
    # A confirmation that is still one-sided keeps the loop going, so say which
    # side is missing before asking for the next move.
    pending = corroboration.pending_confirmations(state, state.get("hypotheses", []))
    if pending:
        user += corroboration.nudge(pending, state)
    call = call_structured(Step, prompts.SYSTEM, user)
    step: Step = call.output
    hyps = _apply_updates(state, step)
    update = {**_account(state, call), "hypotheses": hyps, "last_note": step.note}

    confirmed = corroboration.corroborated(state, hyps)
    one_sided = corroboration.pending_confirmations(state, hyps)
    if confirmed:
        return {**update, "pending_call": None, "stop_reason": "confirmed by symptom + change evidence"}
    if (step.conclude or step.next_call is None) and one_sided and steps_left > 1:
        # Don't stop on half the evidence while budget remains.
        side = one_sided[0][1]
        if step.next_call is None:
            forced = corroboration.next_missing_side_call(state, side)
            if forced is None:
                return {**update, "pending_call": None,
                        "stop_reason": f"stopped with {'symptom' if side == 'change' else 'change'} evidence only"}
            return {**update, "pending_call": forced,
                    "last_note": f"{step.note} - checking {side} evidence first"}
        update["last_note"] = f"{step.note} (need {side} evidence)"
    elif step.conclude or step.next_call is None:
        # Never write a root cause without having looked at what changed, even
        # when the model stopped without confirming anything.
        if not corroboration.change_history_checked(state) and steps_left > 1:
            forced = corroboration.next_missing_side_call(state, "change")
            if forced is not None:
                return {**update, "pending_call": forced,
                        "last_note": f"{step.note} - checking what changed first"}
        why = "model concluded" if step.conclude else "no next call"
        return {**update, "pending_call": None, "stop_reason": why}
    if not prompts.open_hypotheses(state) and not [h for h in hyps if h.status == HypothesisStatus.open]:
        return {**update, "pending_call": None, "stop_reason": "no open hypotheses"}
    nc = step.next_call
    if repeated_tool_call(state, nc.tool, nc.args):
        return {**update, "pending_call": None, "stop_reason": "loop detected (repeated tool call)"}
    return {**update, "pending_call": nc.model_dump()}


def route_after_decide(state: InvestigationState) -> str:
    return "run_tool" if state.get("pending_call") else "write_report"


def run_tool_node(state: InvestigationState) -> dict:
    pc = state["pending_call"]
    res, latency, err = run_tool(pc["tool"], pc["args"])
    rec = ToolRecord(step=state["step"] + 1, tool=pc["tool"], args=pc["args"], tests_hypothesis=pc["tests_hypothesis"],
                     why=pc["why"], summary=res.summary, refs=res.refs, latency_ms=round(latency, 1), error=err)
    return {"tool_calls": state["tool_calls"] + [rec], "step": state["step"] + 1, "pending_call": None,
            "last_note": f"{pc['tool']}: {pc['why']}"}


def write_report(state: InvestigationState) -> dict:
    call = call_structured(
        Report, prompts.SYSTEM,
        prompts.REPORT.format(case=prompts.render_case(state), stop_reason=state.get("stop_reason")),
        small=os.getenv("AGENT_CHEAP_REPORT", "0") == "1",  # the case file already holds the reasoning
    )
    r: Report = call.output
    known = {ref for c in state.get("tool_calls", []) for ref in c["refs"]}
    dropped = [c for c in r.supporting_evidence if c.source_ref not in known]
    r.supporting_evidence = [c for c in r.supporting_evidence if c.source_ref in known]
    if dropped:
        r.unchecked_areas.append(f"{len(dropped)} citation(s) removed by validator: not present in evidence ledger")
    if not r.supporting_evidence and r.confidence != "low":
        r.confidence = "low"
    if not corroboration.change_history_checked(state):
        r.unchecked_areas.append("what changed (deploys/commits) was never queried")
    return {**_account(state, call), "report": r, "last_note": f"Report: {r.root_cause[:80]}"}


def create_github_issue(state: InvestigationState) -> dict:
    # Phase 5: real GitHub issue after human approval. Until then: no-op.
    return {"github_issue_url": None, "last_note": "GitHub issue creation not enabled yet"}


def elapsed(state: InvestigationState) -> float:
    return time.time() - state["budget"]["started_at"]
