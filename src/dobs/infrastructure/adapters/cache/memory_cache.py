from __future__ import annotations

from dobs.application.ports.cache import StatementCachePort
from dobs.domain.entities.statement import Statement


class MemoryStatementCache(StatementCachePort):
    def __init__(self) -> None:
        self._store: dict[str, Statement] = {}

    async def get(self, key: str) -> Statement | None:
        return self._store.get(key)

    async def put(self, key: str, statement: Statement) -> None:
        self._store[key] = statement

    async def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def clear(self) -> int:
        count = len(self._store)
        self._store.clear()
        return count

    async def keys(self, limit: int = 200) -> list[dict]:
        items = list(self._store.keys())[:limit]
        return [{"key": k, "created_at": None, "reconciled": False} for k in items]

    async def stats(self) -> dict:
        return {"total": len(self._store), "backend": "memory"}
