import re
from collections import Counter

from pydantic import BaseModel, Field

from mcp_server.config import get_settings
from mcp_server.db import fetch, parse_window


class LogLine(BaseModel):
    id: int
    ts: str
    level: str
    message: str
    path: str | None = None
    method: str | None = None
    status: int | None = None
    trace_id: str | None = None
    region: str | None = None
    duration_ms: float | None = None
    stack_tail: str | None = Field(default=None, description="last lines of the stack trace, if any")


class ErrorSignature(BaseModel):
    signature: str
    count: int
    first_seen: str
    last_seen: str
    example_log_id: int


class LogSearchResult(BaseModel):
    window_start: str
    window_end: str
    total_matching: int
    counts_by_level: dict[str, int]
    lines: list[LogLine]
    top_error_signatures: list[ErrorSignature]
    sample_trace_ids: list[str]


_ID_RE = re.compile(r"\b\w*\d[\w.]*\b")  # any token containing a digit: ids, hashes, numbers


def signature_of(message: str) -> str:
    """Collapse ids / hashes / numbers so identical errors group together."""
    return _ID_RE.sub("#", message)[:160]


def search_logs(
    query: str | None = None,
    service: str = "checkout",
    level: str | None = None,
    path: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
) -> LogSearchResult:
    """Search the target app's structured logs in a time window (ISO timestamps,
    default: last 30 minutes). `query` matches message or stack trace text;
    `level` is INFO/WARN/ERROR; `path` filters by endpoint. Returns matching
    lines, counts by level, grouped error signatures and sample trace IDs."""
    s = get_settings()
    start_dt, end_dt = parse_window(start, end)
    limit = max(1, min(limit, s.max_log_lines))

    where = ["service = :service", "ts >= :start", "ts <= :end"]
    params: dict = {"service": service, "start": start_dt, "end": end_dt}
    if level:
        where.append("level = :level")
        params["level"] = level.upper()
    if path:
        where.append("path = :path")
        params["path"] = path
    if query:
        where.append("(message LIKE :q OR stack LIKE :q)")
        params["q"] = f"%{query}%"
    w = " AND ".join(where)

    by_level = {r["level"]: r["n"] for r in fetch(f"SELECT level, COUNT(*) AS n FROM app_logs WHERE {w} GROUP BY level", **params)}
    total = sum(by_level.values())

    rows = fetch(
        f"SELECT id, ts, level, message, path, method, status, trace_id, region, duration_ms, stack "
        f"FROM app_logs WHERE {w} ORDER BY ts DESC LIMIT :limit",
        **params, limit=limit,
    )
    lines = [
        LogLine(
            **{k: r[k] for k in ("id", "level", "message", "path", "method", "status", "trace_id", "region", "duration_ms")},
            ts=str(r["ts"]),
            stack_tail="\n".join(r["stack"].strip().splitlines()[-6:]) if r.get("stack") else None,
        )
        for r in rows
    ]

    # Error signatures over the whole window (not just the returned page)
    err_rows = fetch(
        f"SELECT id, ts, message FROM app_logs WHERE {w} AND level = 'ERROR' ORDER BY ts",
        **params,
    )
    groups: dict[str, list[dict]] = {}
    for r in err_rows:
        groups.setdefault(signature_of(r["message"]), []).append(r)
    signatures = sorted(
        (
            ErrorSignature(
                signature=sig, count=len(rs), first_seen=str(rs[0]["ts"]),
                last_seen=str(rs[-1]["ts"]), example_log_id=rs[-1]["id"],
            )
            for sig, rs in groups.items()
        ),
        key=lambda e: -e.count,
    )[:10]

    trace_ids = [t for t, _ in Counter(r["trace_id"] for r in rows if r["trace_id"]).most_common(5)]

    return LogSearchResult(
        window_start=start_dt.isoformat(), window_end=end_dt.isoformat(),
        total_matching=total, counts_by_level=by_level, lines=lines,
        top_error_signatures=signatures, sample_trace_ids=trace_ids,
    )
