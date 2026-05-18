from __future__ import annotations

from dobs.application.ports.event_bus import EventBusPort
from dobs.application.ports.job_queue import JobStorePort


class StoreEventBus(EventBusPort):
    def __init__(self, /, *, store: JobStorePort, job_id: str) -> None:
        self._store = store
        self._job_id = job_id

    async def publish(self, event_name: str, data: dict[str, object]) -> None:
        await self._store.write_event(self._job_id, {"event": event_name, "data": data})
