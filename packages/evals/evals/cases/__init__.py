from pathlib import Path

import yaml
from pydantic import BaseModel

CASES_DIR = Path(__file__).parent


class GroundTruth(BaseModel):
    category: str
    culprit: str | None
    is_external: bool


class IncidentInput(BaseModel):
    title: str
    description: str


class EvalCase(BaseModel):
    id: str
    scenario: str
    incident: IncidentInput
    ground_truth: GroundTruth


def load_cases() -> list[EvalCase]:
    return [
        EvalCase.model_validate(yaml.safe_load(p.read_text()))
        for p in sorted(CASES_DIR.glob("*.yaml"))
    ]
