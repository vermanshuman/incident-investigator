"""Call one investigation tool directly (what the agent calls internally).

    python tools.py search_logs level=ERROR limit=5
    python tools.py get_deploy_events
"""

from _local import run_in
import sys

sys.exit(run_in("mcp-server", "python", ["-m", "mcp_server.cli", *sys.argv[1:]]))
