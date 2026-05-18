"""Parity test: extract the SAME statement with two backends and compare.

Runs the Apr 2025 statement through Anthropic Claude and Ollama qwen2.5,
then diffs the structured outputs field-by-field. Used to validate that
the local LLM is a viable replacement.

Usage:
    python examples/parity_test.py            # Apr 2025 (default)
    python examples/parity_test.py 1          # statement index (0-based)
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from extractor.ingest import ingest  # noqa: E402
from extractor.segment import split_statements  # noqa: E402
from extractor.pipeline import _process_segment  # noqa: E402
from extractor.cache import StatementCache  # noqa: E402
from extractor.backends import get_backend  # noqa: E402


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _log_event(prefix: str):
    def log(name, data):
        _stderr(f"  [{prefix}][{name}] {data}")
    return log


def _run_one(segment, backend, cache):
    t0 = time.time()
    statement = _process_segment(segment, backend, log_event=_log_event(backend.name), cache=cache)
    elapsed = time.time() - t0
    return statement, elapsed


def main() -> int:
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    pdf = ROOT / "Binder2_Redacted.pdf"
    txt = ROOT / "ixonia_ocr.txt"

    text = ingest(str(pdf), str(txt) if txt.exists() else None)
    segs = split_statements(text)
    if idx >= len(segs):
        _stderr(f"ERROR: index {idx} out of range (have {len(segs)} statements)")
        return 1
    seg = segs[idx]
    _stderr(f"\n=== Parity test on statement {idx}: "
            f"{seg.period_start_raw} acct {seg.account_hint} ({len(seg.text):,} chars) ===\n")

    cache = StatementCache(ROOT / "out/cache.db")

    # Anthropic
    _stderr(">>> Running ANTHROPIC backend")
    anth_backend = get_backend("anthropic")
    anth_stmt, anth_elapsed = _run_one(seg, anth_backend, cache)

    # Ollama
    _stderr("\n>>> Running OLLAMA backend")
    olla_backend = get_backend("ollama")
    olla_stmt, olla_elapsed = _run_one(seg, olla_backend, cache)

    # Diff
    _stderr("\n=== Comparison ===")

    def cmp(label, a, b, fmt=str):
        equal = a == b
        mark = "[OK] " if equal else "[!!] "
        _stderr(f"  {mark}{label:<22}  anthropic={fmt(a):<25} ollama={fmt(b)}")
        return equal

    score = 0
    total = 0
    for label, get in [
        ("bank", lambda s: s.account.bank),
        ("account_last4", lambda s: s.account.account_last4),
        ("period.start", lambda s: s.account.period.start),
        ("period.end", lambda s: s.account.period.end),
        ("beginning_balance", lambda s: s.summary.beginning_balance),
        ("ending_balance", lambda s: s.summary.ending_balance),
        ("deposits_total", lambda s: s.summary.deposits_total),
        ("deposits_count", lambda s: s.summary.deposits_count),
        ("withdrawals_total", lambda s: s.summary.withdrawals_total),
        ("withdrawals_count", lambda s: s.summary.withdrawals_count),
        ("transactions count", lambda s: len(s.transactions)),
        ("reconciled?", lambda s: s.reconciliation.ok if s.reconciliation else None),
    ]:
        total += 1
        if cmp(label, get(anth_stmt), get(olla_stmt)):
            score += 1

    _stderr(f"\n  Field match: {score}/{total}")
    _stderr(f"  Wall clock:  anthropic={anth_elapsed:.1f}s  ollama={olla_elapsed:.1f}s")

    # Quick "etalon" check on the summary side for both
    from datetime import date
    d = date.fromisoformat(anth_stmt.account.period.start)
    label = d.strftime("%b %Y")
    _stderr(f"\n  Etalon for {label} acct {anth_stmt.account.account_last4}:")
    _stderr(f"    anthropic reconciliation: {'OK' if anth_stmt.reconciliation.ok else 'MISMATCH'}")
    _stderr(f"    ollama    reconciliation: {'OK' if olla_stmt.reconciliation.ok else 'MISMATCH'}")
    if not olla_stmt.reconciliation.ok:
        _stderr("    ollama issues:")
        for i in olla_stmt.reconciliation.issues:
            _stderr(f"      - {i}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
