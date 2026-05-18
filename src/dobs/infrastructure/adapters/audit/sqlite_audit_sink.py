from __future__ import annotations

import hashlib
import json

from dobs.application.ports.audit_sink import AuditSinkPort
from dobs.domain.entities.audit_record import AuditRecord
from dobs.infrastructure.persistence.sqlite_session import SqliteSessionFactory

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at         TIMESTAMP,
    tier                TEXT,
    backend             TEXT,
    source_filename     TEXT,
    source_sha256       TEXT,
    statement_count     INTEGER,
    reconciled_count    INTEGER,
    transactions_count  INTEGER,
    total_cost_usd      REAL,
    elapsed_s           REAL,
    prompts_hash        TEXT,
    operator            TEXT,
    client_ip           TEXT,
    metadata_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_started ON audit_log(started_at);
CREATE INDEX IF NOT EXISTS idx_audit_sha     ON audit_log(source_sha256);
"""

_COLS = [
    "id",
    "started_at",
    "finished_at",
    "tier",
    "backend",
    "source_filename",
    "source_sha256",
    "statement_count",
    "reconciled_count",
    "transactions_count",
    "total_cost_usd",
    "elapsed_s",
    "prompts_hash",
    "operator",
    "client_ip",
]


def _prompts_hash() -> str:
    try:
        from dobs.domain.prompts import REPAIR_SYSTEM, SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM

        h = hashlib.sha256()
        for p in (SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM):
            h.update(p.encode("utf-8"))
        return h.hexdigest()[:16]
    except ImportError:
        return ""


class SqliteAuditSink(AuditSinkPort):
    def __init__(self, /, *, sessions: SqliteSessionFactory) -> None:
        self._sessions = sessions

    async def record(self, started_at: float, record: AuditRecord) -> int:
        async with self._sessions.session() as session:
            cursor = await session.execute(
                "INSERT INTO audit_log "
                "(started_at, finished_at, tier, backend, source_filename, "
                "source_sha256, statement_count, reconciled_count, "
                "transactions_count, total_cost_usd, elapsed_s, "
                "prompts_hash, operator, client_ip, metadata_json) "
                "VALUES (datetime(?, 'unixepoch'), datetime('now'), "
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    started_at,
                    record.tier,
                    record.backend,
                    record.source_filename,
                    record.source_sha256,
                    record.statement_count,
                    record.reconciled_count,
                    record.transactions_count,
                    record.total_cost_usd,
                    record.elapsed_s,
                    record.prompts_hash,
                    record.operator,
                    record.client_ip,
                    json.dumps(record.metadata),
                ),
            )
            return cursor.lastrowid or 0

    async def recent(self, limit: int = 50) -> list[dict[str, object]]:
        async with self._sessions.read_only() as session:
            async with session.execute(
                f"SELECT {', '.join(_COLS)} FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(zip(_COLS, row)) for row in rows]
