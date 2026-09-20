"""Run tests for every Python package. Exit code 1 if any fail.

    python test.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGES = ["apps/api", "apps/target-app", "packages/agent", "packages/mcp-server", "packages/evals"]

failed = []
for pkg in PACKAGES:
    print(f"\n=== {pkg}")
    r = subprocess.run(["uv", "run", "pytest", "-q"], cwd=os.path.join(ROOT, pkg), shell=(os.name == "nt"))
    if r.returncode != 0:
        failed.append(pkg)

print("\nFAILED: " + ", ".join(failed) if failed else "\nAll packages passed")
sys.exit(1 if failed else 0)
