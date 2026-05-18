import uuid

from dobs.infrastructure.adapters.cache.memory_cache import MemoryStatementCache as MemoryCache
from dobs.infrastructure.adapters.cache.resolver import open_cache
from dobs.domain.entities.statement import Statement
from dobs.domain.value_objects.account import Account
from dobs.domain.value_objects.period import Period
from dobs.domain.value_objects.summary import Summary


def _statement() -> Statement:
    return Statement(
        oid=str(uuid.uuid4()),
        account=Account(
            bank="X",
            account_last4="0001",
            period=Period(start="2025-01-01", end="2025-01-31"),
        ),
        summary=Summary(
            beginning_balance=0,
            ending_balance=0,
            deposits_total=0,
            withdrawals_total=0,
        ),
        transactions=[],
    )


async def test_memory_cache_roundtrip():
    c = MemoryCache()
    s = _statement()
    assert await c.get("k") is None
    await c.put("k", s)
    out = await c.get("k")
    assert out is not None
    assert out.account.account_last4 == "0001"


async def test_memory_cache_stats():
    c = MemoryCache()
    await c.put("a", _statement())
    await c.put("b", _statement())
    stats = await c.stats()
    assert stats == {"total": 2, "backend": "memory"}


async def test_open_cache_dispatch(tmp_path):
    mem = await open_cache("memory")
    assert mem.__class__.__name__ == "MemoryStatementCache"
    sqlite_obj = await open_cache(str(tmp_path / "test.db"))
    assert sqlite_obj.__class__.__name__ == "SqliteStatementCache"
    sqlite_prefixed = await open_cache("sqlite:" + str(tmp_path / "test2.db"))
    assert sqlite_prefixed.__class__.__name__ == "SqliteStatementCache"
    empty = await open_cache("")
    assert empty.__class__.__name__ == "MemoryStatementCache"


async def test_redis_url_falls_back_when_unreachable(tmp_path):
    out = await open_cache("redis://127.0.0.1:12/0")
    assert out is not None
    assert out.__class__.__name__ in {"SqliteStatementCache", "RedisStatementCache"}
