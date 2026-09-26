"""The repair layer for models that double-encode structured answers."""

from agent.llm import _parse_raw
from agent.schemas import HypothesisSet, Triage

GOOD = {"hypotheses": [{"id": "H1", "statement": "s", "category": "bad_deploy"},
                       {"id": "H2", "statement": "s", "category": "config"},
                       {"id": "H3", "statement": "s", "category": "external"}]}


class Raw:
    def __init__(self, args=None, content=None):
        self.tool_calls = [{"args": args}] if args is not None else []
        self.content = content


def test_plain_args():
    assert len(_parse_raw(HypothesisSet, Raw(args=GOOD)).hypotheses) == 3


def test_whole_object_as_json_string_in_field():
    import json
    # the failure seen in the live run
    assert _parse_raw(HypothesisSet, Raw(args={"hypotheses": json.dumps(GOOD)})) is not None


def test_list_sent_as_json_string():
    import json
    assert _parse_raw(HypothesisSet, Raw(args={"hypotheses": json.dumps(GOOD["hypotheses"])})) is not None


def test_json_in_text_content():
    import json
    raw = Raw(content=json.dumps({"error_signature": "500s", "affected_endpoints": ["/x"],
                                  "started_at": None, "severity": "high"}))
    assert _parse_raw(Triage, raw).error_signature == "500s"


def test_unrecoverable_returns_none():
    assert _parse_raw(HypothesisSet, Raw(args={"nope": 1})) is None


def test_over_long_fields_are_trimmed_not_rejected():
    from agent.schemas import Report, Step

    step = Step.model_validate({"note": "x" * 500})
    assert len(step.note) == 160 and step.note.endswith("…")

    report = Report.model_validate({
        "summary": "s" * 900, "customer_impact": "c", "timeline": [f"t{i}" for i in range(20)],
        "root_cause": "r", "confidence": "low", "supporting_evidence": [],
        "ruled_out": [], "fix": {"summary": "f" * 400, "change": "", "rollback": "r"},
        "unchecked_areas": [], "is_external": False,
    })
    assert len(report.summary) == 400
    assert len(report.timeline) == 6
    assert len(report.fix.summary) == 200  # nested model trimmed too
