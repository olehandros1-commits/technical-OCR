from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand
from dobs.application.dto.serializers import serialize_results
from dobs.infrastructure.adapters.jobs.memory_job_store import MemoryJobStore


class AsyncioJobQueue:
    def __init__(
        self,
        /,
        *,
        store: MemoryJobStore,
        handler_factory: Callable[[], Awaitable[Any] | object],
    ) -> None:
        self._store = store
        self._handler_factory = handler_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def enqueue(self, job_id: str, command: ExtractStatementCommand) -> None:
        handler = self._handler_factory()
        task = asyncio.create_task(self._run(job_id, handler, command))
        self._tasks[job_id] = task

    async def _run(
        self,
        job_id: str,
        handler: Any,
        command: ExtractStatementCommand,
    ) -> None:
        try:
            results = await handler(command)
            await self._store.write_result(job_id, result=serialize_results(results))
        except Exception as exc:
            await self._store.write_result(job_id, error=str(exc))
