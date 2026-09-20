"""Read-only access to the target database.

SQLite: opened with `mode=ro` at the driver level, so even a bug in the SQL
guard cannot write. Postgres: uses whatever role the URL carries; deploy with
a SELECT-only role (see infra/db/init.sql) and a statement_timeout.
"""

import sqlite3
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, text

from mcp_server.config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    url = s.target_database_url
    if url.startswith("sqlite"):
        path = url.removeprefix("sqlite:///")

        def connect():
            return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)

        engine = create_engine("sqlite://", creator=connect)

        @event.listens_for(engine, "before_cursor_execute")
        def _arm_timeout(conn, *_):
            # Statement timeout: the progress handler aborts the query once the
            # deadline passes. Re-armed per statement so pooled connections work.
            deadline = time.monotonic() + s.statement_timeout_seconds
            conn.connection.dbapi_connection.set_progress_handler(
                lambda: 1 if time.monotonic() > deadline else 0, 10_000
            )

        return engine

    engine = create_engine(url, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def _set_timeout(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute(f"SET statement_timeout = {int(s.statement_timeout_seconds * 1000)}")
        cur.execute("SET default_transaction_read_only = on")
        cur.close()

    return engine


def parse_window(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    """ISO strings -> UTC-naive datetimes (how the target app stores them).
    Defaults to the last `default_window_minutes`."""
    now = datetime.now(UTC)
    end_dt = datetime.fromisoformat(end) if end else now
    start_dt = (
        datetime.fromisoformat(start)
        if start
        else end_dt - timedelta(minutes=get_settings().default_window_minutes)
    )
    return _naive_utc(start_dt), _naive_utc(end_dt)


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def fetch(sql: str, **params) -> list[dict]:
    with get_engine().connect() as conn:
        result = conn.execute(text(sql), params)
        return [dict(r._mapping) for r in result]
