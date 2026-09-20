"""Fixture: a throwaway target DB + git repo that look like Phase 1 output."""

import os
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

SCHEMA = """
CREATE TABLE app_logs (id INTEGER PRIMARY KEY, ts DATETIME, level TEXT, service TEXT, message TEXT,
  trace_id TEXT, path TEXT, method TEXT, status INTEGER, duration_ms REAL, region TEXT, stack TEXT, extra JSON);
CREATE TABLE metrics_samples (id INTEGER PRIMARY KEY, ts DATETIME, metric TEXT, path TEXT, value REAL);
CREATE TABLE deploy_events (id INTEGER PRIMARY KEY, ts DATETIME, kind TEXT, ref TEXT, summary TEXT, actor TEXT);
CREATE TABLE orders (id TEXT PRIMARY KEY, cart_id TEXT, total REAL, shipping_country TEXT, status TEXT,
  provider_ref TEXT, created_at DATETIME);
"""


def _ts(minutes_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).replace(tzinfo=None).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )


@pytest.fixture(scope="session")
def target(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("target")
    db_path = root / "checkout.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    # healthy traffic 20..11 minutes ago, then a deploy, then errors
    for i in range(20, 10, -1):
        conn.execute("INSERT INTO app_logs (ts, level, service, message, path, method, status, trace_id) VALUES (?,?,?,?,?,?,?,?)",
                     (_ts(i), "INFO", "checkout", "POST /checkout -> 200", "/checkout", "POST", 200, f"t{i}"))
        conn.execute("INSERT INTO metrics_samples (ts, metric, path, value) VALUES (?,?,?,?)", (_ts(i), "error_rate", "/checkout", 0.0))
    conn.execute("INSERT INTO deploy_events (ts, kind, ref, summary, actor) VALUES (?,?,?,?,?)",
                 (_ts(10.5), "deploy", "abc123def456", "Remove redundant validation", "Rahul Mehta"))
    for i in range(10, 0, -1):
        for order in ("aa11", "bb22"):
            conn.execute("INSERT INTO app_logs (ts, level, service, message, path, method, status, trace_id, stack) VALUES (?,?,?,?,?,?,?,?,?)",
                         (_ts(i), "ERROR", "checkout", f"Unhandled exception: AttributeError for order {order}", "/checkout", "POST", 500, f"e{i}{order}",
                          "Traceback\n  File \"app/routers/checkout.py\", line 53\nAttributeError: 'NoneType' object has no attribute 'country'"))
        conn.execute("INSERT INTO metrics_samples (ts, metric, path, value) VALUES (?,?,?,?)", (_ts(i), "error_rate", "/checkout", 0.33))
    conn.execute("INSERT INTO orders VALUES ('o1','c1',42.0,'IN','paid','ch_1',?)", (_ts(5),))
    conn.execute("INSERT INTO orders VALUES ('o2','c2',99.0,'DE','failed',NULL,?)", (_ts(4),))
    conn.commit()
    conn.close()

    repo = root / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "Priya Nair", "GIT_AUTHOR_EMAIL": "p@x",
           "GIT_COMMITTER_NAME": "Priya Nair", "GIT_COMMITTER_EMAIL": "p@x"}

    def git(*a):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "main")
    (repo / "checkout.py").write_text("if addr is None:\n    raise ValueError\nprint(addr.country)\n")
    git("add", "-A"); git("commit", "-q", "-m", "Add null check")
    (repo / "checkout.py").write_text("print(addr.country)\n")
    git("add", "-A"); git("commit", "-q", "-m", "Remove redundant validation")

    os.environ["TARGET_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["TARGET_REPO_PATH"] = str(repo)
    from mcp_server.config import get_settings
    from mcp_server.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    return {"db": db_path, "repo": repo}
