from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand
from dobs.infrastructure.adapters.jobs.memory_job_store import MemoryJobStore


class AsyncioJobQueue:
    def __init__(
        self,
        /,
        *,
        store: MemoryJobStore,
        handler_factory: Callable[[], Awaitable | object],
    ) -> None:
        self._store = store
        self._handler_factory = handler_factory
        self._tasks: dict[str, asyncio.Task] = {}

    async def enqueue(self, job_id: str, command: ExtractStatementCommand) -> None:
        handler = self._handler_factory()
        task = asyncio.create_task(self._run(job_id, handler, command))
        self._tasks[job_id] = task

    async def _run(self, job_id: str, handler, command: ExtractStatementCommand) -> None:
        try:
            results = await handler(command)
            from dobs.presentation.api.http.v1.extraction.router import _serialize_results

            await self._store.write_result(job_id, result=_serialize_results(results))
        except Exception as exc:
            await self._store.write_result(job_id, error=str(exc))
