"""Shared launcher for the dev shortcuts (dev/fault/tools/investigate/evals).

Builds the environment the local (no-Docker) setup needs: target repo path,
SQLite URL, and whatever is in .env. We load .env here rather than passing
uv's --env-file because Windows shells mangle the backslashes in that path.
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def _parse_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if value[:1] in {'"', "'"}:  # quoted: keep as-is, '#' allowed inside
                value = value[1:].split(value[0])[0]
            else:  # unquoted: everything from the first '#' is a comment
                value = value.split("#")[0].strip()
            if value:
                values[key.strip()] = value
    return values


def local_env() -> dict[str, str]:
    env = {
        **os.environ,
        **_parse_env_file(os.path.join(ROOT, ".env")),
        "TARGET_REPO_PATH": os.path.join(ROOT, "target-repo"),
        "TARGET_DATABASE_URL": "sqlite:///" + os.path.join(ROOT, "data", "checkout.db").replace("\\", "/"),
        "TARGET_APP_URL": "http://localhost:8080",
        "TARGET_RESTART_FLAG": os.path.join(ROOT, "data", "restart-target"),
    }
    # An activated venv would make uv warn and ignore the package's own env.
    env.pop("VIRTUAL_ENV", None)
    return env


def run_in(package: str, command: str, args: list[str] | None = None) -> int:
    """Run `uv run --directory packages/<package> <command> [args]`."""
    cmd = ["uv", "run", "--directory", os.path.join("packages", package), command, *(args or [])]
    return subprocess.run(cmd, cwd=ROOT, env=local_env(), check=False).returncode


def main(package: str, command: str) -> None:
    sys.exit(run_in(package, command, sys.argv[1:]))
