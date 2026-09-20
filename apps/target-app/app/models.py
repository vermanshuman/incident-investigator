"""Checkout service tables.

Business:      products, carts, cart_items, orders
Observability: app_logs, metrics_samples, deploy_events   (read by the investigator's tools)
Runtime:       runtime_state                              (provider status, flags)
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class Product(Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Float)
    stock: Mapped[int] = mapped_column(Integer, default=100)


class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_uuid)
    region: Mapped[str] = mapped_column(String(10), default="in-west")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    items: Mapped[list["CartItem"]] = relationship(back_populates="cart", cascade="all, delete")


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cart_id: Mapped[str] = mapped_column(ForeignKey("carts.id"), index=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"))
    qty: Mapped[int] = mapped_column(Integer)

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_uuid)
    cart_id: Mapped[str] = mapped_column(ForeignKey("carts.id"))
    total: Mapped[float] = mapped_column(Float)
    shipping_country: Mapped[str] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|paid|failed
    provider_ref: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AppLog(Base):
    __tablename__ = "app_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    level: Mapped[str] = mapped_column(String(8), index=True)
    service: Mapped[str] = mapped_column(String(20), default="checkout")
    message: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(16), index=True)
    path: Mapped[str | None] = mapped_column(String(100))
    method: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    region: Mapped[str | None] = mapped_column(String(10))
    stack: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)


class MetricSample(Base):
    __tablename__ = "metrics_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    metric: Mapped[str] = mapped_column(String(40), index=True)
    path: Mapped[str] = mapped_column(String(100), default="*")  # "*" = all endpoints
    value: Mapped[float] = mapped_column(Float)


class DeployEvent(Base):
    __tablename__ = "deploy_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # deploy|config_change|migration|flag_change
    ref: Mapped[str] = mapped_column(String(80))  # commit sha, migration id, flag name
    summary: Mapped[str] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(String(60))


class RuntimeState(Base):
    """Key/value state that is NOT in git: provider health, rotated keys, flags."""

    __tablename__ = "runtime_state"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
