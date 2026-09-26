"""Record and replay LLM calls so a demo costs nothing.

With LLM_RECORD=<file> every structured call is appended to a JSONL cassette.
With LLM_REPLAY=<file> the cassette answers instead of the API, so the same
investigation can be re-run, demoed and filmed with zero API calls.

Matching is deliberately forgiving. Prompts contain a timestamp and the
evidence ledger, so they are never byte-identical between runs: an exact
prompt match is preferred, but the fallback is the next unused recording of
the same schema, in order. That reproduces the recorded investigation while
the tools still run live against the target app.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

CASSETTE_DIR_ENV = "LLM_CASSETTE_DIR"


def _resolve(value: str) -> Path:
    """Relative cassette paths resolve against the project root, not the cwd
    uv happens to run the package from."""
    path = Path(value)
    base = os.getenv(CASSETTE_DIR_ENV)
    return path if path.is_absolute() or not base else Path(base) / path


def _key(schema_name: str, model: str, system: str, user: str) -> str:
    digest = hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()[:16]
    return f"{schema_name}:{model}:{digest}"


def record_path() -> Path | None:
    p = os.getenv("LLM_RECORD")
    return _resolve(p) if p else None


def replay_path() -> Path | None:
    p = os.getenv("LLM_REPLAY")
    return _resolve(p) if p else None


class MissingRecording(RuntimeError):
    """Replay was requested but this call is not in the cassette."""


def _load(path: Path) -> list[dict]:
    if not path.exists():
        raise MissingRecording(f"cassette not found: {path}")
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


_entries: dict[Path, list[dict]] = {}
_used: dict[Path, set[int]] = {}


def reset() -> None:
    """Forget loaded cassettes and which entries were consumed."""
    _entries.clear()
    _used.clear()


def lookup(schema_name: str, model: str, system: str, user: str) -> dict:
    path = replay_path()
    if path is None:
        raise MissingRecording("no LLM_REPLAY cassette configured")
    if path not in _entries:
        _entries[path] = _load(path)
        _used[path] = set()
    rows, used = _entries[path], _used[path]

    wanted = _key(schema_name, model, system, user)
    digest = wanted.rsplit(":", 1)[1]
    same_schema = [i for i, r in enumerate(rows) if r.get("schema") == schema_name]

    # 1. exact prompt match  2. same prompt, any model  3. next unused of this schema
    for i in same_schema:
        if rows[i].get("key") == wanted:
            used.add(i)
            return rows[i]
    for i in same_schema:
        if str(rows[i].get("key", "")).endswith(digest):
            used.add(i)
            return rows[i]
    for i in same_schema:
        if i not in used:
            used.add(i)
            return rows[i]

    raise MissingRecording(
        f"cassette {path.name} has no unused {schema_name} recording left "
        f"({len(same_schema)} present, all consumed). The replayed run took more "
        "steps than the recorded one - re-record it with LLM_RECORD."
    )


def save(schema_name: str, model: str, system: str, user: str, payload: dict[str, Any],
         usage: dict[str, Any]) -> None:
    path = record_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "key": _key(schema_name, model, system, user),
        "schema": schema_name,
        "model": model,
        "output": payload,
        "usage": usage,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
