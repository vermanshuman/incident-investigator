from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import provider
from app.config import get_settings
from app.db import get_db
from app.logging import log_event
from app.models import Cart, Order, Product

router = APIRouter(prefix="/checkout", tags=["checkout"])


class Address(BaseModel):
    line1: str
    city: str
    country: str
    region: str | None = None


class CheckoutRequest(BaseModel):
    cart_id: str
    shipping_address: Address | None = None
    payment_method: str = "card"


class CheckoutResponse(BaseModel):
    order_id: str
    total: float
    shipping_fee: float
    status: str
    provider_ref: str | None = None


def _shipping_fee(country: str, subtotal: float) -> float:
    s = get_settings()
    if country.upper() == "IN":
        return 0.0
    if subtotal >= s.free_shipping_threshold:
        return 0.0
    return s.shipping_fee_international


@router.post("", response_model=CheckoutResponse)
def checkout(body: CheckoutRequest, request: Request, db: Session = Depends(get_db)) -> CheckoutResponse:
    cart = db.get(Cart, body.cart_id)
    if cart is None:
        raise HTTPException(404, "cart not found")
    if not cart.items:
        raise HTTPException(400, "cart is empty")

    # Store-pickup orders arrive without a shipping address; they must be
    # routed through /pickup instead of delivery checkout.
    if body.shipping_address is None:
        raise HTTPException(400, "shipping_address is required for delivery orders")

    subtotal = sum(i.qty * i.product.price for i in cart.items)
    country = body.shipping_address.country.upper()
    fee = _shipping_fee(country, subtotal)
    total = round(subtotal + fee, 2)

    # Reserve inventory
    for item in cart.items:
        product = db.get(Product, item.sku)
        if product.stock < item.qty:
            raise HTTPException(409, f"insufficient stock for {item.sku}")
        product.stock -= item.qty

    order = Order(cart_id=cart.id, total=total, shipping_country=country)
    db.add(order)
    db.flush()

    trace_id = getattr(request.state, "trace_id", None)
    try:
        ref = provider.charge(db, order.id, total)
    except provider.ProviderError as exc:
        order.status = "failed"
        db.commit()
        log_event(
            "ERROR", f"payment provider error for order {order.id}: {exc}",
            trace_id=trace_id, path="/checkout", provider_status=exc.status, order_id=order.id,
        )
        raise HTTPException(502, f"payment failed: {exc}") from exc

    order.status = "paid"
    order.provider_ref = ref
    db.commit()
    log_event("INFO", f"order {order.id} paid {total} via {body.payment_method}",
              trace_id=trace_id, path="/checkout", order_id=order.id, country=country)
    return CheckoutResponse(order_id=order.id, total=total, shipping_fee=fee,
                            status="confirmed", provider_ref=ref)
