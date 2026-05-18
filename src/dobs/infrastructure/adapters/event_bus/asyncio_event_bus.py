from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from dobs.application.ports.event_bus import EventBusPort


class AsyncioEventBus(EventBusPort):
    def __init__(
        self,
        /,
        *,
        max_buffered: int = 10000,
    ) -> None:
        self._max_buffered = max_buffered
        self._queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue(maxsize=max_buffered)

    async def publish(self, event_name: str, data: dict) -> None:
        try:
            self._queue.put_nowait((event_name, data))
        except asyncio.QueueFull:
            pass

    async def subscribe(self) -> AsyncGenerator[tuple[str, dict], None]:
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item

    async def close(self) -> None:
        await self._queue.put(None)
