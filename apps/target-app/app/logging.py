"""Structured JSON logging + request metrics.

Every log line goes to stdout as JSON AND to the app_logs table so the
investigator's search_logs tool can query by time window, level and path.
Recent request samples are kept in memory for the metrics sampler.
"""

import json
import logging
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import UTC, datetime

from prometheus_client import Counter, Histogram
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.db import LogSessionLocal
from app.models import AppLog

REQUESTS = Counter("http_requests_total", "Requests", ["method", "path", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Latency", ["method", "path"])

# (ts, path, status, duration_ms) for the last few minutes; consumed by metrics.py
RECENT_REQUESTS: deque[tuple[float, str, int, float]] = deque(maxlen=20_000)
_recent_lock = threading.Lock()

logger = logging.getLogger("checkout")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

_PERSISTED_FIELDS = {"trace_id", "path", "method", "status", "duration_ms", "region", "stack"}


def _persist(record: dict) -> None:
    try:
        with LogSessionLocal() as db:
            db.add(
                AppLog(
                    ts=datetime.fromisoformat(record["ts"]),
                    level=record["level"],
                    service=record["service"],
                    message=record["message"],
                    extra={k: v for k, v in record.items()
                           if k not in _PERSISTED_FIELDS | {"ts", "level", "service", "message"}},
                    **{k: record.get(k) for k in _PERSISTED_FIELDS},
                )
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 - logging must never break the request
        logger.error(json.dumps({"level": "ERROR", "message": f"log persist failed: {exc}"}))


def log_event(level: str, message: str, **fields) -> None:
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "level": level,
        "service": "checkout",
        "message": message,
        **fields,
    }
    logger.info(json.dumps(record, default=str))
    _persist(record)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("x-trace-id", uuid.uuid4().hex[:16])
        region = request.headers.get("x-region")
        request.state.trace_id = trace_id
        start = time.perf_counter()
        status = 500
        error: dict | None = None
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception as exc:
            error = {
                "message": f"Unhandled exception: {type(exc).__name__}: {exc}",
                "stack": traceback.format_exc(),
            }
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            # Route template ("/cart/{cart_id}") not the raw URL, so metrics
            # and log filters group by endpoint instead of by id.
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            if not path.startswith("/metrics") and path != "/health":
                REQUESTS.labels(request.method, path, status).inc()
                LATENCY.labels(request.method, path).observe(elapsed_ms / 1000)
                with _recent_lock:
                    RECENT_REQUESTS.append((time.time(), path, status, elapsed_ms))
                common = {
                    "trace_id": trace_id, "path": path, "method": request.method,
                    "status": status, "duration_ms": elapsed_ms, "region": region,
                    "url": request.url.path,
                }
                if error:
                    await run_in_threadpool(
                        log_event, "ERROR", error["message"], stack=error["stack"], **common
                    )
                level = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
                await run_in_threadpool(
                    log_event, level, f"{request.method} {path} -> {status}", **common
                )
