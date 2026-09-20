from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Cart, CartItem, Product

router = APIRouter(prefix="/cart", tags=["cart"])


class CartItemIn(BaseModel):
    sku: str
    qty: int = Field(ge=1, default=1)


class CartCreate(BaseModel):
    items: list[CartItemIn]
    region: str = "in-west"


class CartItemOut(BaseModel):
    sku: str
    name: str
    qty: int
    unit_price: float


class CartOut(BaseModel):
    cart_id: str
    region: str
    items: list[CartItemOut]
    subtotal: float


def _to_out(cart: Cart) -> CartOut:
    items = [
        CartItemOut(sku=i.sku, name=i.product.name, qty=i.qty, unit_price=i.product.price)
        for i in cart.items
    ]
    return CartOut(
        cart_id=cart.id,
        region=cart.region,
        items=items,
        subtotal=round(sum(i.qty * i.unit_price for i in items), 2),
    )


@router.post("", response_model=CartOut, status_code=201)
def create_cart(body: CartCreate, db: Session = Depends(get_db)) -> CartOut:
    cart = Cart(region=body.region)
    for item in body.items:
        if db.get(Product, item.sku) is None:
            raise HTTPException(404, f"unknown sku {item.sku}")
        cart.items.append(CartItem(sku=item.sku, qty=item.qty))
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return _to_out(cart)


@router.get("/{cart_id}", response_model=CartOut)
def get_cart(cart_id: str, db: Session = Depends(get_db)) -> CartOut:
    cart = db.get(Cart, cart_id)
    if cart is None:
        raise HTTPException(404, "cart not found")
    return _to_out(cart)
