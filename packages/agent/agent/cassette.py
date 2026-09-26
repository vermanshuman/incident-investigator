"""Record and replay LLM calls so a demo costs nothing.

Every structured call is keyed by (schema, model, prompt hash). With
LLM_RECORD=<file> the response is appended to a JSONL cassette; with
LLM_REPLAY=<file> the cassette answers instead of the API, so the same
investigation can be re-run, demoed and filmed with zero API calls.

Replay is keyed on the prompt, so it survives code changes that do not alter
the prompts. When a key is missing, replay says so instead of silently
falling through to a paid call.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

CASSETTE_DIR_ENV = "LLM_CASSETTE_DIR"


def _key(schema_name: str, model: str, system: str, user: str) -> str:
    digest = hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()[:16]
    return f"{schema_name}:{model}:{digest}"


def record_path() -> Path | None:
    p = os.getenv("LLM_RECORD")
    return Path(p) if p else None


def replay_path() -> Path | None:
    p = os.getenv("LLM_REPLAY")
    return Path(p) if p else None


class MissingRecording(RuntimeError):
    """Replay was requested but this call is not in the cassette."""


def _load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    entries: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries[row["key"]] = row  # later entries win, so re-recording updates
    return entries


_cache: dict[Path, dict[str, dict]] = {}


def lookup(schema_name: str, model: str, system: str, user: str) -> dict:
    path = replay_path()
    if path is None:
        raise MissingRecording("no LLM_REPLAY cassette configured")
    if path not in _cache:
        _cache[path] = _load(path)
    entries = _cache[path]
    key = _key(schema_name, model, system, user)
    if key not in entries:
        # Model-agnostic fallback: the same prompt recorded with another model.
        digest = key.rsplit(":", 1)[1]
        for k, row in entries.items():
            if k.startswith(f"{schema_name}:") and k.endswith(digest):
                return row
        raise MissingRecording(
            f"{schema_name} call not in cassette {path.name} (key {key}). "
            "Record a run first: LLM_RECORD=<file> python investigate.py ..."
        )
    return entries[key]


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
