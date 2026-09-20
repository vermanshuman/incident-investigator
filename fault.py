"""Shortcut for the fault injector with the same env as dev.py.

    python fault.py list
    python fault.py apply s01_null_check
    python fault.py reset
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
env = {
    **os.environ,
    "TARGET_REPO_PATH": os.path.join(ROOT, "target-repo"),
    "TARGET_DATABASE_URL": "sqlite:///" + os.path.join(ROOT, "data", "checkout.db").replace("\\", "/"),
    "TARGET_APP_URL": "http://localhost:8080",
    "TARGET_RESTART_FLAG": os.path.join(ROOT, "data", "restart-target"),
}
sys.exit(subprocess.run(["uv", "run", "--directory", "apps/target-app", "inject-fault", *sys.argv[1:]],
                        cwd=ROOT, env=env, shell=(os.name == "nt"), check=False).returncode)
