"""Subscription changes, with Stripe when it is configured.

Stripe is optional on purpose. Without `STRIPE_SECRET_KEY` a plan change is
applied directly and marked `simulated`, so the billing flow can be run and
demonstrated without credentials - the same approach the GitHub action takes.

Test mode is the intended setting even when keys are present: `sk_test_...`
with Stripe's published test cards.
"""

from __future__ import annotations

import os

import httpx
from pydantic import BaseModel, Field

from app.core.plans import Plan
from app.models import Organization

STRIPE_API = "https://api.stripe.com/v1"
TIMEOUT = 15.0


class CheckoutResult(BaseModel):
    plan: str
    checkout_url: str | None = Field(
        default=None, description="send the customer here; null when no payment is needed")
    applied: bool = Field(description="True when the plan changed now rather than on a webhook")
    simulated: bool = Field(description="True when Stripe was not called")
    message: str


def is_configured() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY"))


def _price_id(plan: Plan) -> str | None:
    return os.getenv(f"STRIPE_PRICE_{plan.key.upper()}")


def start_checkout(org: Organization, plan: Plan) -> CheckoutResult:
    # Downgrades and free plans never need a payment page.
    if plan.price_usd_month == 0:
        return CheckoutResult(plan=plan.key, applied=True, simulated=not is_configured(),
                              message=f"Switched to {plan.name}.")

    if not is_configured() or not _price_id(plan):
        reason = "STRIPE_SECRET_KEY not set" if not is_configured() else f"STRIPE_PRICE_{plan.key.upper()} not set"
        return CheckoutResult(
            plan=plan.key, applied=True, simulated=True,
            message=f"Simulated upgrade to {plan.name} ({reason}). No payment was taken.")

    base = os.getenv("APP_BASE_URL", "http://localhost:3000")
    response = httpx.post(
        f"{STRIPE_API}/checkout/sessions",
        headers={"Authorization": f"Bearer {os.environ['STRIPE_SECRET_KEY']}"},
        data={
            "mode": "subscription",
            "line_items[0][price]": _price_id(plan),
            "line_items[0][quantity]": 1,
            "success_url": f"{base}/settings?upgraded={plan.key}",
            "cancel_url": f"{base}/settings",
            "client_reference_id": org.id,
            "metadata[org_id]": org.id,
            "metadata[plan]": plan.key,
        },
        timeout=TIMEOUT,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Stripe returned {response.status_code}: {response.text[:200]}")
    session = response.json()
    # The plan changes when Stripe confirms payment, not when we send the user.
    return CheckoutResult(plan=plan.key, checkout_url=session["url"], applied=False, simulated=False,
                          message=f"Complete payment to move to {plan.name}.")


def verify_webhook(payload: bytes, signature: str | None) -> dict:
    """Parse a Stripe webhook, verifying the signature when a secret is set."""
    import hashlib
    import hmac
    import json

    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if secret:
        if not signature:
            raise ValueError("missing Stripe-Signature header")
        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        timestamp, received = parts.get("t"), parts.get("v1")
        expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
        if not received or not hmac.compare_digest(expected, received):
            raise ValueError("signature does not match")
    return json.loads(payload)
