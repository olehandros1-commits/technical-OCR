from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from dobs.application.ports.review_store import Decision, ReviewStorePort


_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_key   TEXT NOT NULL,
    tx_index        INTEGER NOT NULL,
    decision        TEXT NOT NULL,
    reviewer        TEXT,
    note            TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_reviews_lookup
    ON reviews(statement_key, tx_index, id DESC);
"""


class SqliteReviewStore(ReviewStorePort):
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

    async def record(
        self,
        *,
        statement_key: str,
        tx_index: int,
        decision: Decision,
        reviewer: str | None = None,
        note: str | None = None,
    ) -> int:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT INTO reviews (statement_key, tx_index, decision, reviewer, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (statement_key, tx_index, decision, reviewer, note),
            )
            await db.commit()
            return cursor.lastrowid

    async def latest_for_statement(self, statement_key: str) -> dict[int, dict]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT tx_index, decision, reviewer, note FROM reviews r1 "
                "WHERE statement_key = ? AND id = ("
                "  SELECT MAX(id) FROM reviews r2 "
                "  WHERE r2.statement_key = r1.statement_key "
                "    AND r2.tx_index = r1.tx_index"
                ")",
                (statement_key,),
            ) as cursor:
                rows = await cursor.fetchall()
        return {
            row[0]: {
                "statement_key": statement_key,
                "tx_index": row[0],
                "decision": row[1],
                "reviewer": row[2],
                "note": row[3],
            }
            for row in rows
        }

    async def history(self, statement_key: str, tx_index: int) -> list[dict]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT decision, reviewer, note FROM reviews "
                "WHERE statement_key = ? AND tx_index = ? "
                "ORDER BY id ASC",
                (statement_key, tx_index),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "statement_key": statement_key,
                "tx_index": tx_index,
                "decision": row[0],
                "reviewer": row[1],
                "note": row[2],
            }
            for row in rows
        ]
