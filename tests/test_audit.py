"""Tests for the audit log."""
import time

from extractor.audit import AuditLog, AuditRecord, _prompts_hash


def test_prompts_hash_stable():
    a = _prompts_hash()
    b = _prompts_hash()
    assert a == b
    assert len(a) == 16


def test_record_and_recent(tmp_path):
    log = AuditLog(tmp_path / "audit.db")
    rec = AuditRecord(
        tier="balanced", backend="anthropic",
        source_filename="x.pdf", source_sha256="deadbeef" * 8,
        statement_count=3, reconciled_count=3,
        transactions_count=42, total_cost_usd=0.05, elapsed_s=12.3,
        operator="ci", client_ip="127.0.0.1",
    )
    rid = log.record(time.time(), rec)
    assert rid >= 1

    rows = log.recent(limit=5)
    assert len(rows) == 1
    row = rows[0]
    assert row["tier"] == "balanced"
    assert row["statement_count"] == 3
    assert row["reconciled_count"] == 3
    assert row["transactions_count"] == 42
    assert row["operator"] == "ci"
    assert row["prompts_hash"] == _prompts_hash()


def test_recent_orders_by_id_desc(tmp_path):
    log = AuditLog(tmp_path / "audit.db")
    for i in range(3):
        log.record(time.time(), AuditRecord(tier=f"t{i}"))
    rows = log.recent(limit=5)
    assert [r["tier"] for r in rows] == ["t2", "t1", "t0"]
