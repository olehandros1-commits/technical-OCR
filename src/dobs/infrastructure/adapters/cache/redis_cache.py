from __future__ import annotations

import json
import os

from dobs.application.ports.cache import StatementCachePort
from dobs.domain.entities.statement import Statement
from dobs.infrastructure.adapters.cache.sqlite_cache import _statement_from_dict, _statement_to_json


class RedisStatementCache(StatementCachePort):
    def __init__(
        self,
        /,
        *,
        url: str,
        ttl_days: float | None = None,
        key_prefix: str = "bse:",
    ) -> None:
        from redis.asyncio import Redis

        self._client: Redis = Redis.from_url(url, decode_responses=True)
        self._key_prefix = key_prefix
        ttl_days = (
            ttl_days if ttl_days is not None else float(os.getenv("EXTRACTOR_CACHE_TTL_DAYS", "30"))
        )
        self._ttl_seconds: int | None = int(ttl_days * 86400) if ttl_days > 0 else None

    def _k(self, key: str) -> str:
        return self._key_prefix + key

    async def get(self, key: str) -> Statement | None:
        payload = await self._client.get(self._k(key))
        if payload is None:
            return None
        return _statement_from_dict(json.loads(payload))

    async def put(self, key: str, statement: Statement) -> None:
        payload = _statement_to_json(statement)
        if self._ttl_seconds:
            await self._client.set(self._k(key), payload, ex=self._ttl_seconds)
        else:
            await self._client.set(self._k(key), payload)

    async def delete(self, key: str) -> bool:
        result = await self._client.delete(self._k(key))
        return bool(result > 0)

    async def clear(self) -> int:
        count = 0
        async for _ in self._client.scan_iter(match=self._k("*"), count=500):
            count += 1
        if count:
            keys = []
            async for k in self._client.scan_iter(match=self._k("*"), count=500):
                keys.append(k)
            if keys:
                await self._client.delete(*keys)
        return count

    async def keys(self, limit: int = 200) -> list[dict[str, object]]:
        result = []
        async for k in self._client.scan_iter(match=self._k("*"), count=500):
            result.append(
                {"key": k[len(self._key_prefix) :], "created_at": None, "reconciled": False}
            )
            if len(result) >= limit:
                break
        return result

    async def stats(self) -> dict[str, object]:
        total = 0
        async for _ in self._client.scan_iter(match=self._k("*"), count=500):
            total += 1
        return {"total": total, "backend": "redis"}
