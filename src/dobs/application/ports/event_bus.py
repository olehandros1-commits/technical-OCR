from __future__ import annotations

from typing import Protocol


class EventBusPort(Protocol):
    async def publish(self, event_name: str, data: dict[str, object]) -> None: ...
