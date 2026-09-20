from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import provider
from app.db import get_db
from app.logging import log_event
from app.models import Order

router = APIRouter(prefix="/payment", tags=["payment"])


class PaymentRequest(BaseModel):
    order_id: str


class PaymentResponse(BaseModel):
    order_id: str
    provider_ref: str
    status: str


@router.post("/retry", response_model=PaymentResponse)
def retry_payment(body: PaymentRequest, request: Request, db: Session = Depends(get_db)) -> PaymentResponse:
    """Retry a failed order's payment."""
    order = db.get(Order, body.order_id)
    if order is None:
        raise HTTPException(404, "order not found")
    if order.status == "paid":
        return PaymentResponse(order_id=order.id, provider_ref=order.provider_ref or "", status="paid")

    trace_id = getattr(request.state, "trace_id", None)
    try:
        ref = provider.charge(db, order.id, order.total)
    except provider.ProviderError as exc:
        log_event("ERROR", f"payment retry failed for order {order.id}: {exc}",
                  trace_id=trace_id, path="/payment/retry", provider_status=exc.status)
        raise HTTPException(502, f"payment failed: {exc}") from exc

    order.status = "paid"
    order.provider_ref = ref
    db.commit()
    return PaymentResponse(order_id=order.id, provider_ref=ref, status="paid")


@router.get("/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)) -> dict:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "order not found")
    return {"order_id": order.id, "total": order.total, "status": order.status,
            "provider_ref": order.provider_ref}
