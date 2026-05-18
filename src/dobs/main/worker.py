from __future__ import annotations

import os

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand
from dobs.infrastructure.adapters.event_bus.store_event_bus import StoreEventBus
from dobs.infrastructure.adapters.jobs.redis_job_store import RedisJobStore
from dobs.main.composition_root import build_container
from dobs.main.config.settings import AppSettings


async def run_extraction(ctx, job_id: str, command_payload: dict) -> dict:
    settings = AppSettings(backend=command_payload.get("backend") or None)
    container = build_container(settings)
    store = RedisJobStore(url=os.getenv("REDIS_URL", "redis://redis:6379/0"))

    event_bus = StoreEventBus(store=store, job_id=job_id)
    container._event_bus = event_bus  # type: ignore[attr-defined]

    handler = container.extract_handler()
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


async def startup(ctx) -> None:
    pass


async def shutdown(ctx) -> None:
    pass


class WorkerSettings:
    functions = [run_extraction]
    on_startup = startup
    on_shutdown = shutdown

    @property
    def redis_settings(self):
        from arq.connections import RedisSettings

        return RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://redis:6379/0"))


def main() -> None:
    from arq.worker import run_worker

    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
