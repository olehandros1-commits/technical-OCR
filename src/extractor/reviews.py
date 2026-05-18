"""HITL (human-in-the-loop) review decisions: persistence layer.

Each row records that a human approved, rejected, or edited a specific
transaction in a specific statement. Reviews are keyed by
(statement_cache_key, transaction_index) so the same statement re-extracted
keeps the audit trail intact.

Schema is intentionally small and append-only -- never overwrite history.
A single "current" decision is the latest row for a (key, idx) pair.
"""
from __future__ import annotations
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal


Decision = Literal["approve", "reject", "edit", "pending"]


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


@dataclass
class Review:
    statement_key: str
    tx_index: int
    decision: Decision
    reviewer: Optional[str] = None
    note: Optional[str] = None


class ReviewStore:
    """Append-only review log, thread-safe."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def record(self, r: Review) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reviews (statement_key, tx_index, decision, "
                "reviewer, note) VALUES (?, ?, ?, ?, ?)",
                (r.statement_key, r.tx_index, r.decision, r.reviewer, r.note),
            )
            return cur.lastrowid

    def latest_for_statement(self, statement_key: str) -> dict[int, Review]:
        """Return the latest decision per tx_index for the statement."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT tx_index, decision, reviewer, note FROM reviews r1 "
                "WHERE statement_key = ? AND id = ("
                "  SELECT MAX(id) FROM reviews r2 "
                "  WHERE r2.statement_key = r1.statement_key "
                "    AND r2.tx_index = r1.tx_index"
                ") ",
                (statement_key,),
            ).fetchall()
        return {
            row[0]: Review(
                statement_key=statement_key,
                tx_index=row[0],
                decision=row[1],
                reviewer=row[2],
                note=row[3],
            )
            for row in rows
        }

    def history(self, statement_key: str, tx_index: int) -> list[Review]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT decision, reviewer, note FROM reviews "
                "WHERE statement_key = ? AND tx_index = ? "
                "ORDER BY id ASC",
                (statement_key, tx_index),
            ).fetchall()
        return [
            Review(
                statement_key=statement_key,
                tx_index=tx_index,
                decision=row[0],
                reviewer=row[1],
                note=row[2],
            )
            for row in rows
        ]
