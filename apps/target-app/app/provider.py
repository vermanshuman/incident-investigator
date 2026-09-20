"""Fake third-party payment provider.

Behaves like a real HTTP dependency (latency, auth, outages) but runs in-process
so the demo has no external calls. Its health lives in runtime_state, outside
git, because a provider outage is not something a deploy causes.
"""

import random
import time

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RuntimeState

PROVIDER_STATUS_KEY = "payment_provider_status"  # up | down | slow
PROVIDER_EXPECTED_KEY = "payment_provider_expected_api_key"


class ProviderError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _state(db: Session, key: str, default: str) -> str:
    row = db.get(RuntimeState, key)
    return row.value if row else default


def charge(db: Session, order_id: str, amount: float) -> str:
    """Charge the card. Returns the provider reference on success."""
    s = get_settings()
    host = s.payment_provider_url.split("/")[2]
    status = _state(db, PROVIDER_STATUS_KEY, "up")
    expected_key = _state(db, PROVIDER_EXPECTED_KEY, s.payment_provider_api_key)

    if status == "down":
        time.sleep(s.payment_provider_timeout_seconds)
        raise ProviderError(504, f"upstream timeout after {s.payment_provider_timeout_seconds}s from {host}")

    if s.payment_provider_api_key != expected_key:
        time.sleep(random.uniform(0.05, 0.12))
        raise ProviderError(401, f"{host} responded 401 Unauthorized: invalid or expired API key")

    latency = random.uniform(0.08, 0.25) if status == "up" else random.uniform(1.0, 1.8)
    time.sleep(latency)
    return f"ch_{order_id}_{random.randint(1000, 9999)}"
