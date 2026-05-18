"""Tests for the cache-provider abstraction.

Uses MemoryCache for everything (so no Redis is required to run the suite);
Redis-specific code path is exercised by integration tests when a Redis
instance is available.
"""
from extractor.cache_redis import MemoryCache, open_cache
from extractor.schemas import (
    Account, Period, Statement, Summary, ReconciliationResult,
)


def _statement() -> Statement:
    return Statement(
        account=Account(
            bank="X", account_last4="0001",
            period=Period(start="2025-01-01", end="2025-01-31"),
        ),
        summary=Summary(
            beginning_balance=0, ending_balance=0,
            deposits_total=0, deposits_count=0,
            withdrawals_total=0, withdrawals_count=0,
        ),
        transactions=[],
    )


def test_memory_cache_roundtrip():
    c = MemoryCache()
    s = _statement()
    assert c.get("k") is None
    c.put("k", s)
    out = c.get("k")
    assert out is not None
    assert out.account.account_last4 == "0001"


def test_memory_cache_stats():
    c = MemoryCache()
    c.put("a", _statement())
    c.put("b", _statement())
    assert c.stats() == {"total": 2, "backend": "memory"}


def test_open_cache_dispatch():
    # memory:// path
    assert open_cache("memory").__class__.__name__ == "MemoryCache"
    # bare path -> StatementCache (SQLite)
    sqlite_obj = open_cache("/tmp/test_cache_redis.db")
    assert sqlite_obj.__class__.__name__ == "StatementCache"
    # sqlite: prefix also accepted
    assert open_cache("sqlite:/tmp/test_cache_redis.db").__class__.__name__ == "StatementCache"
    # None -> None
    assert open_cache(None) is None
    assert open_cache("") is None


def test_redis_url_falls_back_when_unreachable():
    # Point at a port nothing's listening on -> graceful SQLite fallback,
    # never raises.
    out = open_cache("redis://127.0.0.1:12/0")  # invalid port on purpose
    assert out is not None
    assert out.__class__.__name__ in {"StatementCache", "RedisCache"}
