"""Audit log: every extraction run is durably recorded.

Schema captures the provenance you need to answer "where did this number
come from" months after the fact: source file hash, tier + model
versions, prompt hash, total cost, latency, RLAIF lessons applied,
operator (if known), client IP. Append-only, never mutated.

This is what makes the system pass an external audit (SOC2 / SOX /
ISO 27001) without a paper trail rebuild project later.
"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from extractor.prompts import SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at     TIMESTAMP,
    tier            TEXT,
    backend         TEXT,
    source_filename TEXT,
    source_sha256   TEXT,
    statement_count INTEGER,
    reconciled_count INTEGER,
    transactions_count INTEGER,
    total_cost_usd  REAL,
    elapsed_s       REAL,
    prompts_hash    TEXT,
    operator        TEXT,
    client_ip       TEXT,
    metadata_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_started ON audit_log(started_at);
CREATE INDEX IF NOT EXISTS idx_audit_sha      ON audit_log(source_sha256);
"""


def _prompts_hash() -> str:
    """Stable fingerprint of all system prompts in use.

    When this changes (you tuned a prompt), audit-log readers can tell
    that all rows after this id used a new prompt version.
    """
    h = hashlib.sha256()
    for p in (SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM):
        h.update(p.encode("utf-8"))
    return h.hexdigest()[:16]


@dataclass
class AuditRecord:
    tier: Optional[str] = None
    backend: Optional[str] = None
    source_filename: Optional[str] = None
    source_sha256: Optional[str] = None
    statement_count: int = 0
    reconciled_count: int = 0
    transactions_count: int = 0
    total_cost_usd: float = 0.0
    elapsed_s: float = 0.0
    prompts_hash: str = field(default_factory=_prompts_hash)
    operator: Optional[str] = None
    client_ip: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class AuditLog:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def record(self, started_at: float, rec: AuditRecord) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO audit_log "
                "(started_at, finished_at, tier, backend, source_filename, "
                "source_sha256, statement_count, reconciled_count, "
                "transactions_count, total_cost_usd, elapsed_s, "
                "prompts_hash, operator, client_ip, metadata_json) "
                "VALUES (datetime(?, 'unixepoch'), datetime('now'), "
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    started_at,
                    rec.tier, rec.backend, rec.source_filename, rec.source_sha256,
                    rec.statement_count, rec.reconciled_count,
                    rec.transactions_count, rec.total_cost_usd, rec.elapsed_s,
                    rec.prompts_hash, rec.operator, rec.client_ip,
                    json.dumps(rec.metadata),
                ),
            )
            return cur.lastrowid

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock, self._connect() as conn:
            cols = [
                "id", "started_at", "finished_at", "tier", "backend",
                "source_filename", "source_sha256", "statement_count",
                "reconciled_count", "transactions_count", "total_cost_usd",
                "elapsed_s", "prompts_hash", "operator", "client_ip",
            ]
            rows = conn.execute(
                f"SELECT {', '.join(cols)} FROM audit_log "
                f"ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(zip(cols, row)) for row in rows]
