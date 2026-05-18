from __future__ import annotations

import os

from dishka import make_async_container

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand
from dobs.infrastructure.adapters.event_bus.store_event_bus import StoreEventBus
from dobs.infrastructure.adapters.jobs.redis_job_store import RedisJobStore
from dobs.main.di import _ReplayingExtractHandler, build_providers


async def run_extraction(ctx, job_id: str, command_payload: dict) -> dict:
    backend = command_payload.get("backend")
    if backend:
        os.environ["EXTRACTOR_BACKEND"] = backend

    store = RedisJobStore(url=os.getenv("REDIS_URL", "redis://redis:6379/0"))
    container = make_async_container(*build_providers())
    try:
        async with container() as scope:
            handler = await scope.get(_ReplayingExtractHandler)
            handler._event_bus = StoreEventBus(store=store, job_id=job_id)
            payload = {k: v for k, v in command_payload.items() if k != "backend"}
            command = ExtractStatementCommand(**payload)
            try:
                results = await handler(command)
                from dobs.presentation.api.http.v1.extraction.router import _serialize_results
                await store.write_result(job_id, result=_serialize_results(results))
                return {"ok": True}
            except Exception as exc:
                await store.write_result(job_id, error=str(exc))
                return {"ok": False, "error": str(exc)}
    finally:
        await container.close()


async def startup(ctx) -> None:
    pass


async def shutdown(ctx) -> None:
    pass


def _build_redis_settings():
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://redis:6379/0"))


class WorkerSettings:
    functions = [run_extraction]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _build_redis_settings()


def main() -> None:
    from arq.worker import run_worker

    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
