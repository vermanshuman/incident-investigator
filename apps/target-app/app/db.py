from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str, pool_size: int, max_overflow: int, pool_timeout: int):
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}
        db_path = url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return engine


_s = get_settings()

# Application pool: what checkout/cart/payment use. Fault scenario s03 shrinks it.
engine = _make_engine(
    _s.target_database_url, _s.db_pool_size, _s.db_max_overflow, _s.db_pool_timeout_seconds
)

# Separate small pool for logs + metrics so observability keeps working when
# the application pool is exhausted (which is exactly what we want to observe).
log_engine = _make_engine(_s.target_database_url, 2, 2, 10)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
LogSessionLocal = sessionmaker(bind=log_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def pool_usage() -> tuple[int, int]:
    """(checked_out, capacity) for the application pool."""
    p = engine.pool
    return p.checkedout(), _s.db_pool_size + _s.db_max_overflow
