from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product, RuntimeState

PRODUCTS = [
    ("SKU-001", "Wireless Mouse", 799.0),
    ("SKU-002", "Mechanical Keyboard", 3499.0),
    ("SKU-003", "USB-C Hub", 1299.0),
    ("SKU-004", "Laptop Stand", 1599.0),
    ("SKU-005", "Webcam 1080p", 2199.0),
    ("SKU-006", "Desk Lamp", 899.0),
]


def seed(db: Session) -> None:
    if db.scalar(select(Product).limit(1)) is None:
        db.add_all([Product(sku=s, name=n, price=p, stock=500) for s, n, p in PRODUCTS])
    if db.get(RuntimeState, "payment_provider_status") is None:
        db.add(RuntimeState(key="payment_provider_status", value="up"))
    db.commit()
