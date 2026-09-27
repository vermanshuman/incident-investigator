"""Core tables (plan section 7).

organizations -> incidents -> runs -> run_events / hypotheses / evidence / reports
knowledge_items holds past incidents and runbooks with pgvector embeddings.
eval_cases / eval_results back the evaluation harness.

Everything tenant-owned carries org_id from the start. There is one org today,
but adding that column later means rewriting every query, so it is here now.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class IncidentStatus(str, enum.Enum):
    open = "open"
    investigating = "investigating"
    awaiting_approval = "awaiting_approval"
    resolved = "resolved"
    closed = "closed"


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"
    rejected = "rejected"


class HypothesisStatus(str, enum.Enum):
    open = "open"
    confirmed = "confirmed"
    refuted = "refuted"
    inconclusive = "inconclusive"


DEFAULT_ORG_ID = "org_demo"


class Organization(Base):
    """The tenant. One row today; the column exists so multi-tenancy is a
    configuration change rather than a migration of every table."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")  # free | pro
    # Usage metering: what a plan limit and an invoice are computed from.
    monthly_run_limit: Mapped[int] = mapped_column(Integer, default=100)
    monthly_cost_limit_usd: Mapped[float] = mapped_column(Float, default=5.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    incidents: Mapped[list["Incident"]] = relationship(back_populates="org")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG_ID)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(Enum(Severity), default=Severity.high)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), default=IncidentStatus.open
    )
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | alert
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    org: Mapped[Organization] = relationship(back_populates="incidents")
    runs: Mapped[list["Run"]] = relationship(back_populates="incident", cascade="all, delete")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG_ID)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.queued)
    thread_id: Mapped[str] = mapped_column(String(64), default=_uuid)  # LangGraph checkpoint
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(60))
    stop_reason: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)
    replayed: Mapped[bool] = mapped_column(default=False)  # cassette run: no API cost

    incident: Mapped[Incident] = relationship(back_populates="runs")
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete", order_by="RunEvent.seq"
    )
    hypotheses: Mapped[list["Hypothesis"]] = relationship(
        back_populates="run", cascade="all, delete"
    )
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="run", cascade="all, delete")
    report: Mapped["Report | None"] = relationship(back_populates="run", cascade="all, delete")


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40))  # node | tool_call | hypothesis_update | approval
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="events")


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))  # bad_deploy | schema | config | external ...
    status: Mapped[HypothesisStatus] = mapped_column(
        Enum(HypothesisStatus), default=HypothesisStatus.open
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_for: Mapped[list] = mapped_column(JSON, default=list)
    evidence_against: Mapped[list] = mapped_column(JSON, default=list)

    run: Mapped[Run] = relationship(back_populates="hypotheses")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    source_ref: Mapped[str] = mapped_column(String(200))  # log id, SHA, query, metric window
    excerpt: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="evidence")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    root_cause: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(10))  # low | medium | high
    fix_proposal: Mapped[str] = mapped_column(Text)
    unchecked_areas: Mapped[list] = mapped_column(JSON, default=list)
    body_markdown: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    github_issue_url: Mapped[str | None] = mapped_column(String(300))

    run: Mapped[Run] = relationship(back_populates="report")


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(20))  # past_incident | runbook
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    item_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    # embedding vector(1536) is added by the pgvector migration in Phase 6
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)  # scenario id
    scenario: Mapped[str] = mapped_column(String(60))
    incident_text: Mapped[str] = mapped_column(Text)
    ground_truth: Mapped[dict] = mapped_column(JSON)  # category, culprit, is_external


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("eval_cases.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    agent_answer: Mapped[dict] = mapped_column(JSON)
    score: Mapped[dict] = mapped_column(JSON)  # category_ok, culprit_ok, evidence_quality, ...
    steps: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    latency_s: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
