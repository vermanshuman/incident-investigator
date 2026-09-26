"""Score one agent answer against ground truth (plan section 10)."""

from pydantic import BaseModel

from agent.schemas import Hypothesis, HypothesisStatus, Report
from evals.cases import GroundTruth


class Score(BaseModel):
    category_ok: bool
    culprit_ok: bool
    external_ok: bool
    citations_ok: bool
    total: float  # 0..1


def score_run(report: Report, hypotheses: list[Hypothesis], truth: GroundTruth) -> Score:
    confirmed = [h for h in hypotheses if h.status == HypothesisStatus.confirmed]
    category = confirmed[0].category if confirmed else ("external" if report.is_external else "")
    category_ok = category == truth.category
    external_ok = report.is_external == truth.is_external
    cited_text = " ".join(f"{c.source_ref} {c.excerpt}" for c in report.supporting_evidence) + " " + report.root_cause
    culprit_ok = truth.culprit is None or truth.culprit in cited_text
    citations_ok = len(report.supporting_evidence) >= (1 if truth.is_external else 2)
    parts = [category_ok, culprit_ok, external_ok, citations_ok]
    return Score(category_ok=category_ok, culprit_ok=culprit_ok, external_ok=external_ok,
                 citations_ok=citations_ok, total=sum(parts) / len(parts))
