from __future__ import annotations

import logging
import os
from typing import Any

from dishka import make_async_container

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand
from dobs.application.dto.serializers import serialize_results
from dobs.infrastructure.adapters.event_bus.context_event_bus import bind_event_bus
from dobs.infrastructure.adapters.event_bus.store_event_bus import StoreEventBus
from dobs.infrastructure.adapters.jobs.redis_job_store import RedisJobStore
from dobs.infrastructure.adapters.replay.replaying_extract_handler import ReplayingExtractHandler
from dobs.main.config.settings import get_settings
from dobs.main.di import build_providers
from dobs.main.logging_setup import configure_logging

log = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    ctx["container"] = make_async_container(*build_providers())
    ctx["redis_url"] = os.getenv("REDIS_URL", "redis://redis:6379/0")
    log.info("worker container built")


async def shutdown(ctx: dict[str, Any]) -> None:
    container = ctx.get("container")
    if container is not None:
        await container.close()
        log.info("worker container closed")


async def run_extraction(
    ctx: dict[str, Any], job_id: str, command_payload: dict[str, Any]
) -> dict[str, Any]:
    backend = command_payload.get("backend")
    if backend:
        os.environ["EXTRACTOR_BACKEND"] = str(backend)

    store = RedisJobStore(url=str(ctx["redis_url"]))
    bus = StoreEventBus(store=store, job_id=job_id)
    payload = {k: v for k, v in command_payload.items() if k != "backend"}
    command = ExtractStatementCommand(**payload)

    container = ctx["container"]
    async with container() as scope:
        handler = await scope.get(ReplayingExtractHandler)
        try:
            with bind_event_bus(bus):
                results = await handler(command)
            await store.write_result(job_id, result=serialize_results(results))
            return {"ok": True}
        except Exception as exc:
            log.exception("job %s failed", job_id)
            await store.write_result(job_id, error=str(exc))
            return {"ok": False, "error": str(exc)}


def _build_redis_settings() -> object:
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://redis:6379/0"))


class WorkerSettings:
    functions = [run_extraction]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _build_redis_settings()
    job_timeout = 1800
    max_tries = 1
    keep_result = 3600
    health_check_interval = 60


def main() -> None:
    from arq.worker import run_worker

    run_worker(WorkerSettings)  # type: ignore[arg-type]  # arq accepts subclasses of WorkerSettingsBase


if __name__ == "__main__":
    main()
