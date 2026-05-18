from __future__ import annotations

from dobs.application.ports.review_store import Decision, ReviewStorePort
from dobs.infrastructure.persistence.sqlite_session import SqliteSessionFactory


REVIEW_SCHEMA = """
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
    def __init__(self, /, *, sessions: SqliteSessionFactory) -> None:
        self._sessions = sessions

    async def record(
        self,
        *,
        statement_key: str,
        tx_index: int,
        decision: Decision,
        reviewer: str | None = None,
        note: str | None = None,
    ) -> int:
        async with self._sessions.session() as session:
            cursor = await session.execute(
                "INSERT INTO reviews (statement_key, tx_index, decision, reviewer, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (statement_key, tx_index, decision, reviewer, note),
            )
            return cursor.lastrowid

    async def latest_for_statement(self, statement_key: str) -> dict[int, dict]:
        async with self._sessions.read_only() as session:
            async with session.execute(
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
        async with self._sessions.read_only() as session:
            async with session.execute(
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
