from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class LessonsStorePort(Protocol):
    @abstractmethod
    async def record(self, pattern_hash: str, hint: str, source: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def top_hints(self, limit: int = 5) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def feedback(self, hint: str, helpful: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stats(self) -> dict:
        raise NotImplementedError
