import pytest

from mcp_server.tools.database import UnsafeQueryError, validate_select


def test_select_gets_limit():
    assert "LIMIT" in validate_select("select * from orders")


def test_rejects_update():
    with pytest.raises(UnsafeQueryError):
        validate_select("update orders set total = 0")


def test_rejects_multiple_statements():
    with pytest.raises(UnsafeQueryError):
        validate_select("select 1; drop table orders")
