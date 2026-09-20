"""Guarded read-only SQL. Defence in depth:
1. connection opened read-only (sqlite mode=ro / postgres read-only role)
2. sqlglot parse: reject anything that is not a single SELECT
3. row limit appended, statement timeout enforced by the connection
"""

import sqlglot
from pydantic import BaseModel
from sqlalchemy import text
from sqlglot import exp

from mcp_server.config import get_settings
from mcp_server.db import get_engine

# Tables the tool advertises to the model (the target app's schema).
SCHEMA_HINT = {
    "products": "sku, name, price, stock",
    "carts": "id, region, created_at",
    "cart_items": "id, cart_id, sku, qty",
    "orders": "id, cart_id, total, shipping_country, status(pending|paid|failed), provider_ref, created_at",
    "app_logs": "id, ts, level, service, message, trace_id, path, method, status, duration_ms, region, stack",
    "metrics_samples": "id, ts, metric, path, value",
    "deploy_events": "id, ts, kind, ref, summary, actor",
    "runtime_state": "key, value, updated_at",
}


class QueryResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    plan: list[str] | None = None


class UnsafeQueryError(ValueError):
    pass


def _dialect() -> str:
    return "sqlite" if get_settings().target_database_url.startswith("sqlite") else "postgres"


def validate_select(sql: str) -> str:
    dialect = _dialect()
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as e:
        raise UnsafeQueryError(f"could not parse SQL: {e}") from e
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        raise UnsafeQueryError("only a single SELECT statement is allowed")
    stmt = statements[0]
    if stmt.find(exp.Command, exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create):
        raise UnsafeQueryError("write or DDL constructs are not allowed")
    max_rows = get_settings().max_rows
    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(max_rows)
    elif int(limit.expression.this) > max_rows:
        stmt.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return stmt.sql(dialect=dialect)


def query_database(sql: str, explain: bool = False) -> QueryResult:
    """Run a read-only SELECT against the target app's database (max 200 rows,
    5s timeout). Tables: products, carts, cart_items, orders, app_logs,
    metrics_samples, deploy_events, runtime_state. Set explain=True to also
    return the query plan (useful for missing-index hypotheses)."""
    safe_sql = validate_select(sql)
    max_rows = get_settings().max_rows
    with get_engine().connect() as conn:
        plan = None
        if explain:
            prefix = "EXPLAIN QUERY PLAN " if _dialect() == "sqlite" else "EXPLAIN "
            plan = [" ".join(str(c) for c in r) for r in conn.execute(text(prefix + safe_sql))]
        result = conn.execute(text(safe_sql))
        columns = list(result.keys())
        rows = [[_cell(v) for v in r] for r in result]
    return QueryResult(
        sql=safe_sql, columns=columns, rows=rows, row_count=len(rows),
        truncated=len(rows) >= max_rows, plan=plan,
    )


def _cell(v):
    return v if isinstance(v, (int, float, str, type(None), bool)) else str(v)
