from __future__ import annotations
from abc import abstractmethod
from typing import Protocol

from src.dobs.domain.entities.statement import Statement


class StatementCachePort(Protocol):
    @abstractmethod
    async def get(self, key: str) -> Statement | None:
        raise NotImplementedError

    @abstractmethod
    async def put(self, key: str, statement: Statement) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def clear(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def keys(self, limit: int = 200) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    async def stats(self) -> dict:
        raise NotImplementedError
