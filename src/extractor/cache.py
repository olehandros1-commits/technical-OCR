"""Content-addressed SQLite cache for extracted statements.

Replaces the earlier per-segment JSON file cache. Benefits:
  * One file per project (out/cache.db) instead of dozens of JSONs.
  * Concurrent-safe via SQLite's WAL.
  * Easy to query history ("how many cache hits this week", "which
    statements have ever failed to reconcile", etc).
  * Stable across moves -- the key is the content hash, not a filename.

The cache is intentionally a thin layer: it stores serialised Statement
objects keyed by an opaque string the pipeline computes from the segment
text. The pipeline encodes the backend name into the key so different
backends do not pollute each other's results.
"""
from __future__ import annotations
import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from extractor.schemas import Statement


_SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reconciled INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_created ON statements(created_at);
"""


class StatementCache:
    """Thread-safe SQLite cache. Use one instance per process."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def get(self, key: str) -> Optional[Statement]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM statements WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return Statement.model_validate(json.loads(row[0]))

    def put(self, key: str, statement: Statement) -> None:
        payload = statement.model_dump_json()
        reconciled = int(
            statement.reconciliation.ok if statement.reconciliation else 0
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO statements (key, payload, reconciled) "
                "VALUES (?, ?, ?)",
                (key, payload, reconciled),
            )

    def stats(self) -> dict:
        """Lightweight inspection helper -- handy for the CLI."""
        with self._lock, self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM statements"
            ).fetchone()[0]
            ok = conn.execute(
                "SELECT COUNT(*) FROM statements WHERE reconciled = 1"
            ).fetchone()[0]
        return {"total": total, "reconciled": ok}

    def delete(self, key: str) -> bool:
        """Forced cache-bust for one statement. Returns True if a row was removed."""
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM statements WHERE key = ?", (key,))
            return cur.rowcount > 0

    def clear(self) -> int:
        """Wipe the whole cache (use with care). Returns count removed."""
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM statements")
            return cur.rowcount

    def keys(self, limit: int = 200) -> list[dict]:
        """List cached keys for tooling / UI debug pane."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT key, created_at, reconciled FROM statements "
                "ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return [
            {"key": k, "created_at": c, "reconciled": bool(r)}
            for k, c, r in rows
        ]
