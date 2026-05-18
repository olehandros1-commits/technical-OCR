from __future__ import annotations
from abc import abstractmethod
from typing import Protocol


class EventBusPort(Protocol):
    @abstractmethod
    async def publish(self, event_name: str, data: dict) -> None:
        raise NotImplementedError
