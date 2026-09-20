"""Call any tool directly from the terminal (for testing without an agent).

    uv run python -m mcp_server.cli search_logs level=ERROR limit=5
    uv run python -m mcp_server.cli get_metrics metric=error_rate path=/checkout
    uv run python -m mcp_server.cli list_commits
    uv run python -m mcp_server.cli get_commit_diff sha=HEAD
    uv run python -m mcp_server.cli query_database "sql=select status, count(*) from orders group by status"
    uv run python -m mcp_server.cli get_deploy_events

Values are parsed as JSON when possible, otherwise as strings.
"""

import json
import sys

from pydantic import BaseModel

from mcp_server.tools import database, deploys, git, incidents, logs, metrics

TOOLS = {
    "search_logs": logs.search_logs,
    "get_metrics": metrics.get_metrics,
    "query_database": database.query_database,
    "search_incidents": incidents.search_incidents,
    "list_commits": git.list_commits,
    "get_commit_diff": git.get_commit_diff,
    "get_deploy_events": deploys.get_deploy_events,
}


def _parse(value: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _dump(obj):
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_dump(o) for o in obj]
    return obj


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in TOOLS:
        print("tools:", ", ".join(TOOLS))
        return 1
    kwargs = {}
    for arg in argv[1:]:
        k, _, v = arg.partition("=")
        kwargs[k] = _parse(v)
    result = TOOLS[argv[0]](**kwargs)
    print(json.dumps(_dump(result), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
