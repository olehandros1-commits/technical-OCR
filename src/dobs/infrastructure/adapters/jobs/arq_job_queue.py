from __future__ import annotations

import dataclasses
import os
from typing import Any

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand


class ArqJobQueue:
    def __init__(self, /, *, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pool: Any = None

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            from arq import create_pool
            from arq.connections import RedisSettings

            settings = RedisSettings.from_dsn(self._redis_url)
            self._pool = await create_pool(settings)
        return self._pool

    async def enqueue(self, job_id: str, command: ExtractStatementCommand) -> None:
        pool = await self._ensure_pool()
        payload = dataclasses.asdict(command)
        await pool.enqueue_job(
            "run_extraction",
            job_id,
            payload,
            _job_id=job_id,
        )


def parse_redis_url() -> str | None:
    return os.getenv("REDIS_URL")
