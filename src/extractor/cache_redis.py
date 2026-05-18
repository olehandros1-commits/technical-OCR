"""Redis-backed cache for the extractor.

Same `get(key) / put(key, statement) / stats()` interface as
[`StatementCache`](cache.py), so the pipeline doesn't care which is in
use. Pick one via:

  EXTRACTOR_CACHE_URL=redis://localhost:6379/0    (Redis)
  EXTRACTOR_CACHE_URL=sqlite:out/cache.db         (SQLite, default)
  EXTRACTOR_CACHE_URL=memory                      (in-process, for tests)

Why Redis:
  * Survives process restarts (so does SQLite).
  * Multiple API workers share a cache (SQLite WAL works on one host;
    Redis works across machines).
  * Trivial TTL eviction (`EXTRACTOR_CACHE_TTL_DAYS`).
"""
from __future__ import annotations
import os
from typing import Optional

from extractor.schemas import Statement


class RedisCache:
    """Drop-in replacement for StatementCache, backed by Redis."""

    def __init__(self, url: str, *, ttl_days: float | None = None,
                 key_prefix: str = "bse:") -> None:
        try:
            import redis  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "RedisCache requires the `redis` package: pip install redis"
            ) from exc
        from redis import Redis
        self.client = Redis.from_url(url, decode_responses=True)
        # Trip the connection eagerly so a bad URL fails on startup, not on first .get().
        self.client.ping()
        self.key_prefix = key_prefix
        ttl_days = ttl_days if ttl_days is not None else float(os.getenv(
            "EXTRACTOR_CACHE_TTL_DAYS", "30"))
        self.ttl_seconds = int(ttl_days * 86400) if ttl_days > 0 else None

    def _k(self, key: str) -> str:
        return self.key_prefix + key

    def get(self, key: str) -> Optional[Statement]:
        payload = self.client.get(self._k(key))
        if payload is None:
            return None
        return Statement.model_validate_json(payload)

    def put(self, key: str, statement: Statement) -> None:
        payload = statement.model_dump_json()
        if self.ttl_seconds:
            self.client.set(self._k(key), payload, ex=self.ttl_seconds)
        else:
            self.client.set(self._k(key), payload)

    def stats(self) -> dict:
        # SCAN-based count -- fine for our scale, doesn't block the server.
        n_total = 0
        for _ in self.client.scan_iter(match=self._k("*"), count=500):
            n_total += 1
        return {"total": n_total, "backend": "redis"}


class MemoryCache:
    """In-process dict cache for tests / pure-stateless use."""
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> Optional[Statement]:
        s = self._store.get(key)
        return Statement.model_validate_json(s) if s else None

    def put(self, key: str, statement: Statement) -> None:
        self._store[key] = statement.model_dump_json()

    def stats(self) -> dict:
        return {"total": len(self._store), "backend": "memory"}


def open_cache(url_or_path: str | None) -> Optional[object]:
    """Resolve `EXTRACTOR_CACHE_URL` / explicit arg into a cache instance.

    Falls back gracefully: bad Redis URL logs a warning and returns the
    SQLite cache so the pipeline never fails just because Redis is down.
    """
    if url_or_path is None or url_or_path == "":
        return None
    if url_or_path == "memory":
        return MemoryCache()
    if url_or_path.startswith("redis://") or url_or_path.startswith("rediss://"):
        import logging
        log = logging.getLogger(__name__)
        try:
            return RedisCache(url_or_path)
        except Exception as e:
            log.warning("Redis cache failed (%s); falling back to SQLite", e)
            from extractor.cache import StatementCache
            from pathlib import Path
            return StatementCache(Path("out/cache.db"))
    # Path -> SQLite
    from extractor.cache import StatementCache
    from pathlib import Path
    if url_or_path.startswith("sqlite:"):
        url_or_path = url_or_path[len("sqlite:"):]
    return StatementCache(Path(url_or_path))
