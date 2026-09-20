"""Shortcut: call an investigation tool against the local target app.

    python tools.py search_logs level=ERROR limit=5
    python tools.py get_metrics metric=error_rate path=/checkout
    python tools.py list_commits
    python tools.py get_deploy_events
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
env = {
    **os.environ,
    "TARGET_REPO_PATH": os.path.join(ROOT, "target-repo"),
    "TARGET_DATABASE_URL": "sqlite:///" + os.path.join(ROOT, "data", "checkout.db").replace("\\", "/"),
}
sys.exit(subprocess.run(["uv", "run", "--directory", "packages/mcp-server", "python", "-m", "mcp_server.cli", *sys.argv[1:]],
                        cwd=ROOT, env=env, shell=(os.name == "nt"), check=False).returncode)
