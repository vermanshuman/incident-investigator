"""Tool registry + compact renderers.

The MCP tools return rich structured data. The model only sees a compact
summary (a few hundred tokens), and every citable item gets a `source_ref`
the model must reuse verbatim when it cites evidence. That is how the report
validator later checks citations are real.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from mcp_server.tools import database, deploys, git, logs, metrics

from agent import cassette
from agent.guardrails import redact

MAX_DIFF_CHARS = 3000


@dataclass
class ToolResult:
    summary: str
    refs: list[str]


def _r_logs(r: logs.LogSearchResult) -> ToolResult:
    lines = [f"window {r.window_start[11:19]}..{r.window_end[11:19]} matched={r.total_matching} by_level={r.counts_by_level}"]
    refs = []
    for s in r.top_error_signatures[:4]:
        ref = f"log:{s.example_log_id}"
        refs.append(ref)
        lines.append(f"- [{ref}] x{s.count} {s.first_seen[11:19]}..{s.last_seen[11:19]}: {s.signature}")
    for ln in r.lines[:3]:
        ref = f"log:{ln.id}"
        refs.append(ref)
        tail = f" | {ln.stack_tail.splitlines()[-1]}" if ln.stack_tail else ""
        lines.append(f"- [{ref}] {ln.ts[11:19]} {ln.level} {ln.method or ''} {ln.path or ''} {ln.status or ''} {ln.message[:120]}{tail}")
    if not r.top_error_signatures and not r.lines:
        lines.append("no matching lines")
    return ToolResult("\n".join(lines), refs)


def _r_metrics(series: list[metrics.MetricSeries]) -> ToolResult:
    if not series:
        return ToolResult("no samples in window", [])
    lines, refs = [], []
    for s in series[:6]:
        ref = f"metric:{s.metric}:{s.path}"
        refs.append(ref)
        cps = "; ".join(f"{c.ts[11:19]} {c.before}->{c.after} ({c.direction})" for c in s.change_points) or "none"
        lines.append(f"- [{ref}] n={len(s.points)} baseline={s.baseline} latest={s.latest} min={s.min} max={s.max} change_points: {cps}")
    return ToolResult("\n".join(lines), refs)


def _r_deploys(evs: list[deploys.DeployEvent]) -> ToolResult:
    if not evs:
        return ToolResult("NO deploys, config changes, migrations or flag changes in the window", [])
    lines, refs = [], []
    for e in evs[:8]:
        ref = f"deploy:{e.ref}"
        refs.append(ref)
        lines.append(f"- [{ref}] {e.ts[11:19]} {e.kind} by {e.actor}: {e.summary}")
    return ToolResult("\n".join(lines), refs)


def _r_commits(cs: list[git.CommitInfo]) -> ToolResult:
    if not cs:
        return ToolResult("no commits in window", [])
    lines, refs = [], []
    for c in cs[:8]:
        ref = f"commit:{c.short_sha}"
        refs.append(ref)
        head = " (DEPLOYED HEAD)" if c.is_head else ""
        lines.append(f"- [{ref}] {c.ts[:16]} {c.author}: {c.message}{head} files={c.files_changed[:4]}")
    return ToolResult("\n".join(lines), refs)


def _r_diff(d: git.CommitDiff) -> ToolResult:
    ref = f"commit:{d.sha[:8]}"
    body = d.diff[:MAX_DIFF_CHARS] + ("\n...[truncated]" if len(d.diff) > MAX_DIFF_CHARS else "")
    return ToolResult(f"[{ref}] {d.author} {d.ts[:16]}: {d.message}\n{body}", [ref])


def _r_query(q: database.QueryResult) -> ToolResult:
    ref = f"query:{q.sql[:80]}"
    rows = "\n".join(str(r) for r in q.rows[:15])
    more = f"\n...({q.row_count} rows)" if q.row_count > 15 else ""
    plan = f"\nplan: {q.plan}" if q.plan else ""
    return ToolResult(f"[{ref}] columns={q.columns}\n{rows}{more}{plan}", [ref])


TOOLS: dict[str, tuple[Callable, Callable]] = {
    "search_logs": (logs.search_logs, _r_logs),
    "get_metrics": (metrics.get_metrics, _r_metrics),
    "get_deploy_events": (deploys.get_deploy_events, _r_deploys),
    "list_commits": (git.list_commits, _r_commits),
    "get_commit_diff": (git.get_commit_diff, _r_diff),
    "query_database": (database.query_database, _r_query),
}

# Short catalogue for the prompt (kept tiny on purpose: it is sent every step)
TOOL_CATALOGUE = """\
search_logs(query?, level?, path?, start?, end?, limit?) - error signatures + sample lines
get_metrics(metric: request_rate|error_rate|p95_latency_ms|db_pool_usage, path?="*", start?, end?, group_by_path?) - baseline/latest/change points
get_deploy_events(start?, end?) - deploys/config/migrations/flags in window
list_commits(start?, end?, paths?, author?, limit?) - commits on deployed branch, HEAD marked
get_commit_diff(sha, path?) - what a commit changed
query_database(sql, explain?) - read-only SELECT on products, carts, cart_items, orders, app_logs, metrics_samples, deploy_events, runtime_state
Times are ISO strings; windows default to the last 30 minutes."""


def run_tool(name: str, args: dict) -> tuple[ToolResult, float, str | None]:
    """Execute a tool; return (result, latency_ms, error). Output is redacted
    before it can reach the model. Under LLM_REPLAY the recorded result is
    returned instead, so a replay needs neither the target app nor its data."""
    if cassette.replay_path() is not None:
        row = cassette.lookup(cassette.tool_schema(name), "-", "", cassette.args_key(args))
        out = row["output"]
        return ToolResult(out["summary"], out["refs"]), out.get("latency_ms", 0.0), out.get("error")

    if name not in TOOLS:
        return ToolResult(f"unknown tool {name}", []), 0.0, "unknown tool"
    fn, render = TOOLS[name]
    t0 = time.perf_counter()
    error: str | None = None
    try:
        raw = fn(**args)
        res = render(raw)
        res.summary = redact(res.summary)
    except Exception as exc:  # noqa: BLE001 - surface tool failures to the model as data
        error = f"{type(exc).__name__}: {exc}"[:300]
        res = ToolResult(f"tool error: {error}", [])
    latency = (time.perf_counter() - t0) * 1000
    cassette.save(cassette.tool_schema(name), "-", "", cassette.args_key(args),
                  {"summary": res.summary, "refs": res.refs, "latency_ms": round(latency, 1), "error": error},
                  {})
    return res, latency, error
