import time
import uuid

from dobs.infrastructure.adapters.audit.sqlite_audit_sink import AUDIT_SCHEMA, SqliteAuditSink
from dobs.domain.entities.audit_record import AuditRecord
from dobs.infrastructure.persistence.sqlite_session import SqliteSessionFactory


def _make_sink(tmp_path):
    sessions = SqliteSessionFactory(db_path=tmp_path / "audit.db", schema=AUDIT_SCHEMA)
    return SqliteAuditSink(sessions=sessions)


async def test_record_and_recent(tmp_path):
    sink = _make_sink(tmp_path)
    rec = AuditRecord(
        oid=str(uuid.uuid4()),
        tier="balanced",
        backend="anthropic",
        source_filename="x.pdf",
        source_sha256="deadbeef" * 8,
        statement_count=3,
        reconciled_count=3,
        transactions_count=42,
        total_cost_usd=0.05,
        elapsed_s=12.3,
        operator="ci",
        client_ip="127.0.0.1",
    )
    rid = await sink.record(time.time(), rec)
    assert rid >= 1

    rows = await sink.recent(limit=5)
    assert len(rows) == 1
    row = rows[0]
    assert row["tier"] == "balanced"
    assert row["statement_count"] == 3
    assert row["reconciled_count"] == 3
    assert row["transactions_count"] == 42
    assert row["operator"] == "ci"


async def test_recent_orders_by_id_desc(tmp_path):
    sink = _make_sink(tmp_path)
    for i in range(3):
        await sink.record(time.time(), AuditRecord(oid=str(uuid.uuid4()), tier=f"t{i}"))
    rows = await sink.recent(limit=5)
    assert [r["tier"] for r in rows] == ["t2", "t1", "t0"]
