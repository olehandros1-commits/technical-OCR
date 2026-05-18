"""Tests for the RLAIF-lite lessons store + repair diagnosis."""
from pathlib import Path

from extractor.prompt_lessons import (
    LessonsStore,
    diagnose_repair,
    lessons_block,
)
from extractor.schemas import ReconciliationResult, Transaction


def _recon(ok: bool, dep_delta: float = 0.0, with_delta: float = 0.0, **kw) -> ReconciliationResult:
    return ReconciliationResult(
        ok=ok,
        deposits_sum=0, withdrawals_sum=0,
        deposits_count_actual=0, withdrawals_count_actual=0,
        deposits_total_delta=dep_delta,
        withdrawals_total_delta=with_delta,
        deposits_count_delta=kw.get("dep_count_delta", 0),
        withdrawals_count_delta=kw.get("with_count_delta", 0),
        balance_equation_delta=kw.get("bal", 0),
        issues=[],
    )


def test_diagnose_side_flip_detected():
    # Mirror-image deltas: +$100 deposits, -$100 withdrawals -> side flip.
    before = _recon(ok=False, dep_delta=100.0, with_delta=-100.0)
    after = _recon(ok=True)
    prev = [Transaction(date="2025-04-01", description="X", deposit=None, withdrawal=100.0)]
    after_txns = [Transaction(date="2025-04-01", description="X", deposit=100.0, withdrawal=None)]
    out = diagnose_repair(before, after, prev, after_txns)
    assert any("mis-classified" in h for _, h in out)


def test_diagnose_missed_check():
    before = _recon(ok=False, with_delta=200.0)
    after = _recon(ok=True)
    prev: list[Transaction] = []
    after_txns = [Transaction(date="2025-04-01", description="CHECK #40788", withdrawal=200.0)]
    out = diagnose_repair(before, after, prev, after_txns)
    assert any("CHECKS PAID" in h or "CHECK #" in h for _, h in out)


def test_diagnose_hallucinated_balance_marker():
    before = _recon(ok=False, dep_delta=-1.0)
    after = _recon(ok=True)
    prev = [Transaction(date="2025-04-01", description="BEGINNING BALANCE $1000",
                        deposit=1000.0)]
    after_txns: list[Transaction] = []
    out = diagnose_repair(before, after, prev, after_txns)
    assert any("BEGINNING BALANCE" in h for _, h in out)


def test_diagnose_no_lessons_when_already_ok():
    before = _recon(ok=True)
    after = _recon(ok=True)
    assert diagnose_repair(before, after, [], []) == []


def test_store_roundtrip(tmp_path: Path):
    store = LessonsStore(tmp_path / "lessons.db")
    store.record("hash1", "hint A", "src1")
    store.record("hash2", "hint B", "src2")
    # Dedupe on (pattern_hash, hint).
    store.record("hash1", "hint A", "src3")
    assert len(store.top_hints(10)) == 2


def test_lessons_block_empty_when_store_empty(tmp_path: Path):
    store = LessonsStore(tmp_path / "lessons.db")
    assert lessons_block(store) == ""


def test_lessons_block_renders_top_hints(tmp_path: Path):
    store = LessonsStore(tmp_path / "lessons.db")
    store.record("a", "alpha", "src")
    store.record("b", "beta", "src")
    block = lessons_block(store, limit=5)
    assert "alpha" in block
    assert "beta" in block
    assert "Lessons from previous extractions" in block


def lessons_str(p, h):
    return f"{p}-{h}"
