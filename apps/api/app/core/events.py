"""Run event bus.

The UI needs events as they happen, so something must carry them from whatever
executes the agent to every open browser. Today that is one process, so an
in-memory fan-out is enough and needs no Redis (and no Docker).

The interface is deliberately the shape of Redis pub/sub - `publish(channel,
event)` and `subscribe(channel)` - so Phase 6 can swap in a Redis-backed bus
for multiple API workers without touching the routers or the agent.

Channels are per run AND per org, so one tenant's stream can never carry
another's events.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

Event = dict[str, Any]

# A subscriber that falls this far behind is dropped rather than allowed to
# grow without bound: a stalled browser tab must not become a memory leak.
QUEUE_LIMIT = 256


def run_channel(org_id: str, run_id: str) -> str:
    return f"org:{org_id}:run:{run_id}"


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event | None]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, event: Event) -> None:
        for queue in list(self._subscribers.get(channel, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer: it will resync from the stored events

    def publish_threadsafe(self, loop: asyncio.AbstractEventLoop, channel: str, event: Event) -> None:
        """Publish from the worker thread the agent runs in (its graph is sync)."""
        asyncio.run_coroutine_threadsafe(self.publish(channel, event), loop)

    async def close(self, channel: str) -> None:
        """Signal end-of-stream to every subscriber of a finished run."""
        for queue in list(self._subscribers.get(channel, ())):
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[asyncio.Queue[Event | None]]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        async with self._lock:
            self._subscribers.setdefault(channel, set()).add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                subs = self._subscribers.get(channel)
                if subs:
                    subs.discard(queue)
                    if not subs:
                        del self._subscribers[channel]

    def subscriber_count(self, channel: str) -> int:
        return len(self._subscribers.get(channel, ()))


bus = EventBus()
