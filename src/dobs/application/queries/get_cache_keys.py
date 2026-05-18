from __future__ import annotations

from dataclasses import dataclass

from dobs.application.ports.cache import StatementCachePort


@dataclass(frozen=True, kw_only=True, slots=True)
class GetCacheKeysQuery:
    limit: int = 200


class GetCacheKeysHandler:
    def __init__(
        self,
        /,
        *,
        cache: StatementCachePort,
    ) -> None:
        self._cache = cache

    async def __call__(self, query: GetCacheKeysQuery) -> list[dict[str, object]]:
        return await self._cache.keys(limit=query.limit)
