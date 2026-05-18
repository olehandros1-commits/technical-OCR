from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class _JobState:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    result: list[dict] | None = None
    error: str | None = None
    done: bool = False


class MemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, _JobState] = {}
        self._lock = asyncio.Lock()

    async def _ensure(self, job_id: str) -> _JobState:
        async with self._lock:
            if job_id not in self._jobs:
                self._jobs[job_id] = _JobState()
            return self._jobs[job_id]

    async def write_event(self, job_id: str, event: dict) -> None:
        state = await self._ensure(job_id)
        await state.queue.put(event)

    async def read_events(self, job_id: str) -> AsyncIterator[dict]:
        state = await self._ensure(job_id)
        while True:
            event = await state.queue.get()
            yield event
            if event.get("event") == "done":
                return

    async def write_result(
        self,
        job_id: str,
        result: list[dict] | None = None,
        error: str | None = None,
    ) -> None:
        state = await self._ensure(job_id)
        state.result = result
        state.error = error
        state.done = True
        await state.queue.put({"event": "done", "data": {}})

    async def read_result(
        self,
        job_id: str,
    ) -> tuple[list[dict] | None, str | None, bool]:
        async with self._lock:
            state = self._jobs.get(job_id)
        if state is None:
            return None, "Job not found", True
        return state.result, state.error, state.done

    async def exists(self, job_id: str) -> bool:
        async with self._lock:
            return job_id in self._jobs
