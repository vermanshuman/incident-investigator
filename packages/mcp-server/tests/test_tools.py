import pytest

from mcp_server.tools import database, deploys, git, logs, metrics


def test_search_logs_groups_errors_and_counts(target):
    r = logs.search_logs(level="ERROR", limit=5)
    assert r.total_matching == 20
    assert r.counts_by_level == {"ERROR": 20}
    assert len(r.lines) == 5
    assert r.lines[0].stack_tail.endswith("has no attribute 'country'")
    assert len(r.top_error_signatures) == 1  # order ids collapsed into one signature
    assert r.top_error_signatures[0].count == 20
    assert "#" in r.top_error_signatures[0].signature


def test_search_logs_query_matches_stack(target):
    r = logs.search_logs(query="checkout.py")
    assert r.total_matching == 20


def test_metrics_change_point_detected(target):
    series = metrics.get_metrics("error_rate", path="/checkout")
    assert len(series) == 1
    s = series[0]
    assert s.baseline == 0.0 and s.latest == 0.33
    assert s.change_points and s.change_points[0].direction == "up"


def test_metrics_rejects_unknown(target):
    with pytest.raises(ValueError):
        metrics.get_metrics("cpu")


def test_deploy_events_in_window(target):
    evs = deploys.get_deploy_events()
    assert len(evs) == 1 and evs[0].ref == "abc123def456"


def test_query_database_select_and_explain(target):
    r = database.query_database("select status, count(*) as n from orders group by status", explain=True)
    assert r.columns == ["status", "n"]
    assert sorted(r.rows) == [["failed", 1], ["paid", 1]]
    assert r.plan


def test_query_database_cannot_write(target):
    with pytest.raises(database.UnsafeQueryError):
        database.query_database("delete from orders")
    # even if the guard were bypassed, the connection is read-only
    from sqlalchemy import text

    from mcp_server.db import get_engine

    with pytest.raises(Exception, match="readonly|read-only"), get_engine().connect() as c:
        c.execute(text("delete from orders"))
        c.commit()


def test_query_limit_is_capped(target):
    assert "LIMIT 200" in database.validate_select("select * from orders limit 5000")


def test_list_commits_and_diff(target):
    commits = git.list_commits()
    assert [c.message for c in commits] == ["Remove redundant validation", "Add null check"]
    assert commits[0].is_head and commits[0].files_changed == ["checkout.py"]
    d = git.get_commit_diff(commits[0].sha)
    assert "-if addr is None:" in d.diff
    assert d.author == "Priya Nair"


def test_statement_timeout_aborts_runaway_query(target, monkeypatch):
    from mcp_server.config import get_settings
    from mcp_server.db import get_engine

    monkeypatch.setenv("STATEMENT_TIMEOUT_SECONDS", "0.2")
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        with pytest.raises(Exception, match="interrupted"):
            # cross join explodes; must be cut off by the timeout, not run to completion
            database.query_database(
                "select count(*) from app_logs a, app_logs b, app_logs c, app_logs d, app_logs e"
            )
    finally:
        monkeypatch.delenv("STATEMENT_TIMEOUT_SECONDS")
        get_settings.cache_clear()
        get_engine.cache_clear()
