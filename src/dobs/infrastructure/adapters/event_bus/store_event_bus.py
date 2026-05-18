from __future__ import annotations


class StoreEventBus:
    def __init__(self, /, *, store, job_id: str) -> None:
        self._store = store
        self._job_id = job_id

    async def publish(self, event_name: str, data: dict) -> None:
        await self._store.write_event(self._job_id, {"event": event_name, "data": data})

    async def emit(self, event_name: str, data: dict) -> None:
        await self.publish(event_name, data)
