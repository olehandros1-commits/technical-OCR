from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


class BackgroundJobRunner:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def spawn(self, coro_factory: Callable[[], Awaitable[None]], *, name: str) -> asyncio.Task:
        task = asyncio.create_task(self._wrap(coro_factory(), name=name), name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _wrap(self, coro: Awaitable[None], *, name: str) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            log.info("background task cancelled: %s", name)
            raise
        except Exception:
            log.exception("background task crashed: %s", name)

    async def shutdown(self, timeout: float = 30.0) -> None:
        if not self._tasks:
            return
        for t in list(self._tasks):
            t.cancel()
        await asyncio.wait(list(self._tasks), timeout=timeout)
