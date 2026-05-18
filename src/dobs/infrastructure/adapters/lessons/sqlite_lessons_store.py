from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from dobs.application.ports.lessons_store import LessonsStorePort


_SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_hash    TEXT NOT NULL,
    hint            TEXT NOT NULL,
    source          TEXT,
    helpful_count   INTEGER DEFAULT 0,
    unhelpful_count INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pattern_hash, hint)
);
CREATE INDEX IF NOT EXISTS idx_lessons_rank
    ON lessons(helpful_count DESC, created_at DESC);
"""


class SqliteLessonsStore(LessonsStorePort):
    def __init__(self, /, *, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = asyncio.Lock()
        self._initialised = False

    async def _ensure_init(self) -> None:
        if self._initialised:
            return
        async with self._init_lock:
            if self._initialised:
                return
            async with aiosqlite.connect(self._db_path) as db:
                await db.executescript(_SCHEMA)
                await db.commit()
            self._initialised = True

    async def record(self, pattern_hash: str, hint: str, source: str | None = None) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO lessons (pattern_hash, hint, source) VALUES (?, ?, ?)",
                    (pattern_hash, hint, source),
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                pass

    async def top_hints(self, limit: int = 5) -> list[str]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT hint FROM lessons "
                "ORDER BY (helpful_count - unhelpful_count) DESC, created_at DESC "
                "LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def feedback(self, hint: str, helpful: bool) -> None:
        await self._ensure_init()
        col = "helpful_count" if helpful else "unhelpful_count"
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"UPDATE lessons SET {col} = {col} + 1 WHERE hint = ?",
                (hint,),
            )
            await db.commit()

    async def stats(self) -> dict:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM lessons") as cursor:
                total = (await cursor.fetchone())[0]
            async with db.execute(
                "SELECT COALESCE(SUM(helpful_count), 0) FROM lessons"
            ) as cursor:
                helpful = (await cursor.fetchone())[0]
            async with db.execute(
                "SELECT COALESCE(SUM(unhelpful_count), 0) FROM lessons"
            ) as cursor:
                unhelpful = (await cursor.fetchone())[0]
        return {"total": total, "helpful": helpful, "unhelpful": unhelpful}
