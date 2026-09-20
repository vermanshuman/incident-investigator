"""Checkout service: the thing the agent investigates.

Endpoints: /cart, /checkout, /payment. Every request writes a structured JSON
log line (stdout + app_logs table) and the sampler writes metrics_samples.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest

from app.db import Base, SessionLocal, engine, pool_usage
from app.logging import RequestLoggingMiddleware
from app.metrics import sampler_loop
from app.routers import cart, checkout, payment
from app.seed import seed


def current_version() -> str:
    """Short git SHA of the checked-out code, or 'dev' when not in a repo."""
    git_dir = Path(__file__).resolve().parents[1] / ".git"
    try:
        head = (git_dir / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            head = (git_dir / head[5:]).read_text().strip()
        return head[:8]
    except OSError:
        return "dev"


VERSION = current_version()  # computed at startup: the code actually running


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    stop = asyncio.Event()
    task = asyncio.create_task(sampler_loop(stop))
    yield
    stop.set()
    await task


app = FastAPI(title="Checkout Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(cart.router)
app.include_router(checkout.router)
app.include_router(payment.router)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return generate_latest().decode()


@app.get("/health")
def health() -> dict:
    used, cap = pool_usage()
    return {"status": "ok", "version": VERSION, "db_pool": f"{used}/{cap}"}
