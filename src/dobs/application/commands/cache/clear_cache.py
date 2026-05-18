from __future__ import annotations

from dataclasses import dataclass

from dobs.application.ports.cache import StatementCachePort


@dataclass(frozen=True, kw_only=True, slots=True)
class ClearCacheCommand:
    pass


class ClearCacheHandler:
    def __init__(
        self,
        /,
        *,
        cache: StatementCachePort,
    ) -> None:
        self._cache = cache

    async def __call__(self, command: ClearCacheCommand) -> int:
        return await self._cache.clear()
