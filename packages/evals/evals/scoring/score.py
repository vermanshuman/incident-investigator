"""Score one agent answer against ground truth (plan section 10)."""

from pydantic import BaseModel

from agent.schemas import Report
from evals.cases import GroundTruth


class Score(BaseModel):
    category_ok: bool
    culprit_ok: bool
    external_ok: bool
    citations_present: bool
    total: float  # 0..1


def score_report(report: Report, truth: GroundTruth, category: str) -> Score:
    culprit_ok = truth.culprit is None or any(
        truth.culprit in c.source_ref for c in report.supporting_evidence
    )
    citations_present = len(report.supporting_evidence) > 0
    external_ok = report.is_external == truth.is_external
    category_ok = category == truth.category

    parts = [category_ok, culprit_ok, external_ok, citations_present]
    return Score(
        category_ok=category_ok,
        culprit_ok=culprit_ok,
        external_ok=external_ok,
        citations_present=citations_present,
        total=sum(parts) / len(parts),
    )
