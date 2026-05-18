from __future__ import annotations

from typing import Protocol

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand


class JobQueuePort(Protocol):
    async def enqueue(self, job_id: str, command: ExtractStatementCommand) -> None: ...


class JobStorePort(Protocol):
    async def write_event(self, job_id: str, event: dict) -> None: ...

    async def read_events(self, job_id: str): ...

    async def write_result(
        self,
        job_id: str,
        result: list[dict] | None = None,
        error: str | None = None,
    ) -> None: ...

    async def read_result(self, job_id: str) -> tuple[list[dict] | None, str | None, bool]: ...

    async def exists(self, job_id: str) -> bool: ...
