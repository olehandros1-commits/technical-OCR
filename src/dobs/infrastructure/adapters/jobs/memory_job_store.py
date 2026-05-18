from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class _JobState:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    result: list[dict] | None = None
    error: str | None = None
    done: bool = False
    finished_at: float | None = None


class MemoryJobStore:
    def __init__(
        self,
        /,
        *,
        ttl_seconds: float = 3600.0,
        max_jobs: int = 1024,
    ) -> None:
        self._jobs: dict[str, _JobState] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds
        self._max_jobs = max_jobs

    async def _ensure(self, job_id: str) -> _JobState:
        async with self._lock:
            self._evict_expired_locked()
            if job_id not in self._jobs:
                self._jobs[job_id] = _JobState()
            return self._jobs[job_id]

    def _evict_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            jid for jid, st in self._jobs.items()
            if st.finished_at is not None and (now - st.finished_at) > self._ttl
        ]
        for jid in expired:
            self._jobs.pop(jid, None)
        if len(self._jobs) > self._max_jobs:
            sorted_finished = sorted(
                (jid for jid, st in self._jobs.items() if st.finished_at is not None),
                key=lambda jid: self._jobs[jid].finished_at or 0,
            )
            for jid in sorted_finished[: len(self._jobs) - self._max_jobs]:
                self._jobs.pop(jid, None)

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
        state.finished_at = time.monotonic()
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
