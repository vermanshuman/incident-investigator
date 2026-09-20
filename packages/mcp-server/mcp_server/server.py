"""MCP server exposing the read-only tool set (plan section 5).

Run: uv run python -m mcp_server.server   (streamable HTTP on :8090/mcp)
"""

from mcp.server.fastmcp import FastMCP

from mcp_server.tools import database, deploys, git, incidents, logs, metrics

mcp = FastMCP("incident-investigator-tools", host="0.0.0.0", port=8090)

mcp.tool()(logs.search_logs)
mcp.tool()(metrics.get_metrics)
mcp.tool()(database.query_database)
mcp.tool()(incidents.search_incidents)
mcp.tool()(git.list_commits)
mcp.tool()(git.get_commit_diff)
mcp.tool()(deploys.get_deploy_events)

# NOTE: create_github_issue is deliberately NOT exposed here. The only write
# action lives in the worker behind the human-approval interrupt.

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
