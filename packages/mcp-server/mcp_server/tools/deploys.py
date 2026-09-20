from pydantic import BaseModel

from mcp_server.db import fetch, parse_window


class DeployEvent(BaseModel):
    ts: str
    kind: str  # deploy | config_change | migration | flag_change
    ref: str  # commit SHA, migration id, flag name
    summary: str
    actor: str | None = None


def get_deploy_events(start: str | None = None, end: str | None = None) -> list[DeployEvent]:
    """Deploys, config changes, migrations and feature-flag changes to the
    target app in a time window (ISO timestamps, default: last 30 minutes),
    newest first. An empty list means nothing was shipped in the window."""
    start_dt, end_dt = parse_window(start, end)
    rows = fetch(
        "SELECT ts, kind, ref, summary, actor FROM deploy_events "
        "WHERE ts >= :start AND ts <= :end ORDER BY ts DESC LIMIT 100",
        start=start_dt, end=end_dt,
    )
    return [DeployEvent(**{**r, "ts": str(r["ts"])}) for r in rows]
