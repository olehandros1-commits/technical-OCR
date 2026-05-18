from __future__ import annotations

import logging
from pathlib import Path

from dobs.application.ports.cache import StatementCachePort

log = logging.getLogger(__name__)


async def open_cache(url: str) -> StatementCachePort:
    from dobs.infrastructure.adapters.cache.memory_cache import MemoryStatementCache
    from dobs.infrastructure.adapters.cache.sqlite_cache import SqliteStatementCache

    if not url:
        return MemoryStatementCache()

    if url == "memory":
        return MemoryStatementCache()

    if url.startswith("redis://") or url.startswith("rediss://"):
        try:
            from dobs.infrastructure.adapters.cache.redis_cache import RedisStatementCache
            cache = RedisStatementCache(url=url)
            await cache._client.ping()
            return cache
        except Exception as exc:
            log.warning("Redis cache unavailable (%s); falling back to SQLite", exc)
            return SqliteStatementCache(db_path=Path("out/cache.db"))

    if url.startswith("sqlite:"):
        url = url[len("sqlite:"):]

    return SqliteStatementCache(db_path=Path(url))
