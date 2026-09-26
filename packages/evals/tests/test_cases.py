from agent.schemas import Citation, Confidence, FixProposal, Hypothesis, HypothesisStatus, Report
from evals.cases import load_cases
from evals.scoring.score import score_run


def test_cases_load_and_include_an_external_one():
    cases = load_cases()
    assert len(cases) >= 3
    assert any(c.ground_truth.is_external for c in cases)


def _report(root_cause, cites, external=False):
    return Report(summary="", customer_impact="", timeline=[], root_cause=root_cause, confidence=Confidence.high,
                  supporting_evidence=[Citation(tool="t", source_ref=c, excerpt="") for c in cites],
                  ruled_out=[], fix=FixProposal(summary="", change="", rollback=""), unchecked_areas=[],
                  is_external=external)


def test_scoring_rewards_correct_culprit_and_external_call():
    truth = next(c for c in load_cases() if c.scenario == "s01_null_check").ground_truth
    hyps = [Hypothesis(id="H1", statement="bad deploy", category="bad_deploy", status=HypothesisStatus.confirmed)]
    good = score_run(_report("commit removed null check in app/routers/checkout.py", ["log:1", "commit:ab"]), hyps, truth)
    assert good.total == 1.0
    bad = score_run(_report("provider outage", ["log:1"], external=True), [], truth)
    assert bad.total < 0.5
