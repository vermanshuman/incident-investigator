"""Plans, usage and the limits that stop a tenant spending without bound.

Usage is metered from runs, which already record model calls, tokens and cost.
The period is the calendar month, which is what an invoice would cover.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Organization, Run, RunStatus


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_usd_month: int
    monthly_run_limit: int
    monthly_cost_limit_usd: float
    seats: int
    blurb: str


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 0, 25, 2.0, 3,
                 "For trying it out: 25 investigations a month."),
    "pro": Plan("pro", "Pro", 49, 500, 50.0, 25,
                "For a team on call: 500 investigations, 25 seats, priority models."),
}
DEFAULT_PLAN = PLANS["free"]


def plan_for(org: Organization) -> Plan:
    return PLANS.get(org.plan, DEFAULT_PLAN)


def apply_plan(org: Organization, plan: Plan) -> None:
    """Limits live on the org so one tenant can be given a bespoke ceiling."""
    org.plan = plan.key
    org.monthly_run_limit = plan.monthly_run_limit
    org.monthly_cost_limit_usd = plan.monthly_cost_limit_usd


def period_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


@dataclass(frozen=True)
class Usage:
    runs: int
    run_limit: int
    cost_usd: float
    cost_limit_usd: float
    tokens: int
    period_start: datetime

    @property
    def runs_left(self) -> int:
        return max(0, self.run_limit - self.runs)

    @property
    def over_run_limit(self) -> bool:
        return self.runs >= self.run_limit

    @property
    def over_cost_limit(self) -> bool:
        return self.cost_usd >= self.cost_limit_usd


def usage_for(db: Session, org: Organization, now: datetime | None = None) -> Usage:
    start = period_start(now)
    scope = (Run.org_id == org.id, Run.started_at >= start)
    runs = db.scalar(select(func.count()).select_from(Run).where(*scope)) or 0
    cost = db.scalar(select(func.sum(Run.cost_usd)).where(*scope)) or 0.0
    tokens = db.scalar(select(func.sum(Run.token_count)).where(*scope)) or 0
    return Usage(
        runs=int(runs), run_limit=org.monthly_run_limit,
        cost_usd=round(float(cost), 4), cost_limit_usd=org.monthly_cost_limit_usd,
        tokens=int(tokens), period_start=start,
    )


class LimitReached(Exception):
    """A plan limit would be exceeded by this action."""

    def __init__(self, message: str, usage: Usage):
        super().__init__(message)
        self.usage = usage


def check_can_start_run(db: Session, org: Organization, replayed: bool = False) -> Usage:
    """Raise if the org has no budget left for another investigation.

    A replay calls no model and costs nothing, so it is never blocked - that
    keeps the demo working on an exhausted free plan.
    """
    usage = usage_for(db, org)
    if replayed:
        return usage
    if usage.over_run_limit:
        raise LimitReached(
            f"Plan limit reached: {usage.runs} of {usage.run_limit} investigations used this month. "
            "Upgrade the plan or wait for the next period.", usage)
    if usage.over_cost_limit:
        raise LimitReached(
            f"Spend limit reached: ${usage.cost_usd:.2f} of ${usage.cost_limit_usd:.2f} this month.",
            usage)
    return usage


def running_count(db: Session, org: Organization) -> int:
    """Concurrency is its own limit: one tenant must not monopolise the workers."""
    return db.scalar(select(func.count()).select_from(Run).where(
        Run.org_id == org.id, Run.status.in_([RunStatus.queued, RunStatus.running]))) or 0
