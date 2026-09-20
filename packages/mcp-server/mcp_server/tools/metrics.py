from statistics import mean, median

from pydantic import BaseModel, Field

from mcp_server.db import fetch, parse_window

METRICS = ["request_rate", "error_rate", "p95_latency_ms", "db_pool_usage"]


class ChangePoint(BaseModel):
    ts: str
    before: float = Field(description="mean of the points before the change")
    after: float = Field(description="mean of the points after the change")
    direction: str  # up | down


class MetricSeries(BaseModel):
    metric: str
    path: str
    points: list[tuple[str, float]]
    min: float
    max: float
    latest: float
    baseline: float = Field(description="median of the first third of the window")
    change_points: list[ChangePoint]


def detect_change_points(points: list[tuple[str, float]], k: int | None = None) -> list[ChangePoint]:
    """Compare the mean of k points before vs k after each index; report the
    strongest shifts. Deliberately simple and explainable."""
    if k is None:
        k = 3 if len(points) >= 8 else 2
    if len(points) < 2 * k:
        return []
    values = [v for _, v in points]
    scale = max(abs(median(values)), 1e-6)
    candidates: list[tuple[float, int]] = []
    for i in range(k, len(values) - k + 1):
        before, after = mean(values[i - k:i]), mean(values[i:i + k])
        shift = abs(after - before)
        if shift >= 0.5 * max(scale, abs(before)) and shift > 1e-6:
            candidates.append((shift, i))
    candidates.sort(reverse=True)
    picked: list[int] = []
    for _, i in candidates:
        if all(abs(i - j) > k for j in picked):
            picked.append(i)
        if len(picked) == 3:
            break
    return [
        ChangePoint(
            ts=points[i][0],
            before=round(mean(values[i - k:i]), 4),
            after=round(mean(values[i:i + k]), 4),
            direction="up" if mean(values[i:i + k]) > mean(values[i - k:i]) else "down",
        )
        for i in sorted(picked)
    ]


def get_metrics(
    metric: str,
    start: str | None = None,
    end: str | None = None,
    path: str | None = None,
    group_by_path: bool = False,
) -> list[MetricSeries]:
    """Fetch a metric time series for the target app. Metrics: request_rate
    (req/s), error_rate (0-1), p95_latency_ms, db_pool_usage (0-1). Default
    window: last 30 minutes. `path` selects one endpoint ("*" = all traffic,
    the default); `group_by_path=True` returns one series per endpoint.
    Each series includes detected change points (when the level shifted)."""
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}; choose from {METRICS}")
    start_dt, end_dt = parse_window(start, end)

    where = "metric = :metric AND ts >= :start AND ts <= :end"
    params = {"metric": metric, "start": start_dt, "end": end_dt}
    if not group_by_path:
        where += " AND path = :path"
        params["path"] = path or "*"
    rows = fetch(f"SELECT ts, path, value FROM metrics_samples WHERE {where} ORDER BY ts", **params)

    by_path: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        by_path.setdefault(r["path"], []).append((str(r["ts"]), float(r["value"])))

    out = []
    for p, pts in sorted(by_path.items()):
        vals = [v for _, v in pts]
        out.append(
            MetricSeries(
                metric=metric, path=p, points=pts,
                min=min(vals), max=max(vals), latest=vals[-1],
                baseline=round(median(vals[: max(1, len(vals) // 3)]), 4),
                change_points=detect_change_points(pts),
            )
        )
    return out
