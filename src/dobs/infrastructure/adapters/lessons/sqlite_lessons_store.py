from __future__ import annotations

import aiosqlite

from dobs.application.ports.lessons_store import LessonsStorePort
from dobs.infrastructure.persistence.sqlite_session import SqliteSessionFactory


LESSONS_SCHEMA = """
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
    def __init__(self, /, *, sessions: SqliteSessionFactory) -> None:
        self._sessions = sessions

    async def record(self, pattern_hash: str, hint: str, source: str | None = None) -> None:
        async with self._sessions.session() as session:
            try:
                await session.execute(
                    "INSERT INTO lessons (pattern_hash, hint, source) VALUES (?, ?, ?)",
                    (pattern_hash, hint, source),
                )
            except aiosqlite.IntegrityError:
                pass

    async def top_hints(self, limit: int = 5) -> list[str]:
        async with self._sessions.read_only() as session:
            async with session.execute(
                "SELECT hint FROM lessons "
                "ORDER BY (helpful_count - unhelpful_count) DESC, created_at DESC "
                "LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def feedback(self, hint: str, helpful: bool) -> None:
        col = "helpful_count" if helpful else "unhelpful_count"
        async with self._sessions.session() as session:
            await session.execute(
                f"UPDATE lessons SET {col} = {col} + 1 WHERE hint = ?",
                (hint,),
            )

    async def stats(self) -> dict:
        async with self._sessions.read_only() as session:
            async with session.execute("SELECT COUNT(*) FROM lessons") as cursor:
                total = (await cursor.fetchone())[0]
            async with session.execute(
                "SELECT COALESCE(SUM(helpful_count), 0) FROM lessons"
            ) as cursor:
                helpful = (await cursor.fetchone())[0]
            async with session.execute(
                "SELECT COALESCE(SUM(unhelpful_count), 0) FROM lessons"
            ) as cursor:
                unhelpful = (await cursor.fetchone())[0]
        return {"total": total, "helpful": helpful, "unhelpful": unhelpful}
