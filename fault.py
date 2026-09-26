"""Fault injector shortcut.

    python fault.py list
    python fault.py apply s01_null_check
    python fault.py reset
"""

import os
import subprocess
import sys

from _local import ROOT, local_env

sys.exit(subprocess.run(["uv", "run", "--directory", os.path.join("apps", "target-app"), "inject-fault", *sys.argv[1:]],
                        cwd=ROOT, env=local_env(), check=False).returncode)
