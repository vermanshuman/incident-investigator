"""Metrics sampler: every N seconds, compute request_rate, error_rate,
p95_latency_ms and db_pool_usage from recent requests and write them to
metrics_samples (overall and per path). The get_metrics tool reads that table."""

import asyncio
import time

from app.config import get_settings
from app.db import LogSessionLocal, pool_usage
from app.logging import RECENT_REQUESTS, _recent_lock
from app.models import MetricSample


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, round(0.95 * len(values)))]


def compute_samples(window_s: int) -> list[MetricSample]:
    cutoff = time.time() - window_s
    with _recent_lock:
        recent = [r for r in RECENT_REQUESTS if r[0] >= cutoff]

    groups: dict[str, list[tuple[float, str, int, float]]] = {"*": recent}
    for r in recent:
        groups.setdefault(r[1], []).append(r)

    samples: list[MetricSample] = []
    for path, rows in groups.items():
        n = len(rows)
        errors = sum(1 for r in rows if r[2] >= 500)
        samples += [
            MetricSample(metric="request_rate", path=path, value=round(n / window_s, 3)),
            MetricSample(metric="error_rate", path=path, value=round(errors / n, 4) if n else 0.0),
            MetricSample(metric="p95_latency_ms", path=path, value=round(_p95([r[3] for r in rows]), 1)),
        ]
    used, cap = pool_usage()
    samples.append(MetricSample(metric="db_pool_usage", path="*", value=round(used / cap, 3) if cap else 0.0))
    return samples


async def sampler_loop(stop: asyncio.Event) -> None:
    interval = get_settings().metrics_sample_interval_seconds
    while not stop.is_set():
        try:
            samples = compute_samples(interval)
            with LogSessionLocal() as db:
                db.add_all(samples)
                db.commit()
        except Exception as exc:  # noqa: BLE001
            print(f"metrics sampler error: {exc}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
