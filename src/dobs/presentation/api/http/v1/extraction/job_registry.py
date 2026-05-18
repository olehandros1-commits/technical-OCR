from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from dobs.application.ports.event_bus import EventBusPort


@dataclass
class JobEntry:
    job_id: str
    event_bus: EventBusPort
    task: asyncio.Task
    result: list[dict] | None = field(default=None)
    error: str | None = field(default=None)
    done: bool = field(default=False)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobEntry] = {}
        self._lock = asyncio.Lock()

    async def register_job(
        self,
        job_id: str,
        event_bus: EventBusPort,
        task: asyncio.Task,
    ) -> None:
        async with self._lock:
            self._jobs[job_id] = JobEntry(job_id=job_id, event_bus=event_bus, task=task)

    async def get_job(self, job_id: str) -> JobEntry | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def result_of(self, job_id: str) -> tuple[list[dict] | None, str | None, bool]:
        async with self._lock:
            entry = self._jobs.get(job_id)
        if entry is None:
            return None, "Job not found", True
        return entry.result, entry.error, entry.done

    async def mark_done(
        self,
        job_id: str,
        result: list[dict] | None = None,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None:
                entry.result = result
                entry.error = error
                entry.done = True


_registry: JobRegistry | None = None


def get_job_registry() -> JobRegistry:
    global _registry
    if _registry is None:
        _registry = JobRegistry()
    return _registry
