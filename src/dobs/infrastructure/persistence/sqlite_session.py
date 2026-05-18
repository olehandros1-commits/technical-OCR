from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


class SqliteSessionFactory:
    def __init__(self, /, *, db_path: Path, schema: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema = schema
        self._init_lock = asyncio.Lock()
        self._initialised = False

    async def _ensure_init(self) -> None:
        if self._initialised:
            return
        async with self._init_lock:
            if self._initialised:
                return  # type: ignore[unreachable]  # double-checked lock pattern
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.executescript(self._schema)
                await conn.commit()
            self._initialised = True

    @asynccontextmanager
    async def session(self) -> AsyncIterator[aiosqlite.Connection]:
        await self._ensure_init()
        conn = await aiosqlite.connect(self._db_path)
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.close()

    @asynccontextmanager
    async def read_only(self) -> AsyncIterator[aiosqlite.Connection]:
        await self._ensure_init()
        conn = await aiosqlite.connect(self._db_path)
        try:
            yield conn
        finally:
            await conn.close()
