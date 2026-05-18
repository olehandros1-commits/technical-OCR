"""RLAIF-lite: persist & inject 'lessons learned' from past repairs.

Idea: every time the repair loop fixes a reconciliation failure, we know
the model made a specific mistake on a recognisable pattern. We record
that mistake as a short, generalisable lesson and inject the top-N
relevant lessons as few-shot hints into the next extraction prompt.

Over time the prompt teaches itself.

Storage: append-only SQLite (`out/lessons.db`). Each lesson has:
  * pattern_hash: stable fingerprint of the mistake category (e.g.
    "missed_check_paid_in_chunk", "wrong_side_for_remote_deposit").
  * hint: one-line guidance to add to subsequent prompts.
  * source: free-form string (e.g. "Apr 2025 acct 4664").
  * helpful_count / unhelpful_count: did adding this hint improve
    first-pass reconciliation later? (Updated by the pipeline.)
  * created_at.

We do NOT replace the static system prompt. We append a small
"# Lessons from previous extractions" block with the top hints, weighted
by helpfulness. The system prompt stays cached; the lessons block is
small enough that even cache-busting it on every call is cheap.

Why call this 'lite': real RLHF/RLAIF retrains weights. We just curate a
shared scratchpad of mistakes. Same direction, far less infrastructure.
"""
from __future__ import annotations
import hashlib
import logging
import sqlite3
import threading
from pathlib import Path

from extractor.schemas import ReconciliationResult, Transaction

log = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_hash    TEXT NOT NULL,
    hint            TEXT NOT NULL,
    source          TEXT,
    helpful_count   INTEGER DEFAULT 0,
    unhelpful_count INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pattern_hash, hint)
);
CREATE INDEX IF NOT EXISTS idx_lessons_rank
    ON lessons(helpful_count DESC, created_at DESC);
"""


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def diagnose_repair(
    before: ReconciliationResult,
    after: ReconciliationResult,
    prev_txns: list[Transaction],
    fixed_txns: list[Transaction],
) -> list[tuple[str, str]]:
    """Translate a successful repair into 0-N (pattern_hash, hint) tuples.

    Each tuple is one generalisable mistake the model made. Heuristics:
      * deposits_count grew by N -> we missed N deposits last time
      * deposits side flipped -> mis-classified deposit vs withdrawal
      * specific descriptions that disappeared between before/after lists
        suggest hallucinated rows we removed
    """
    lessons: list[tuple[str, str]] = []
    if not before or before.ok or not after.ok:
        return lessons

    # ---- side flip ----
    dep_total_delta = before.deposits_total_delta
    with_total_delta = before.withdrawals_total_delta
    if abs(dep_total_delta + with_total_delta) < 0.02 and abs(dep_total_delta) > 1.0:
        pattern = "side_flip_dep_vs_with"
        hint = (
            "Past mistake: deposits were mis-classified as withdrawals on "
            "rows whose amount appeared in the Withdrawals column but with "
            "a leading transfer description. Re-check the column alignment "
            "for TRNSFR / REMOTE DEPOSIT rows."
        )
        lessons.append((_hash(pattern), hint))

    # ---- missed checks-paid ----
    desc_before = {t.description for t in prev_txns}
    desc_after = {t.description for t in fixed_txns}
    new_descs = desc_after - desc_before
    if any("CHECK #" in d for d in new_descs):
        pattern = "missed_checks_paid"
        hint = (
            "Past mistake: a CHECK #NNNNN row from the CHECKS PAID section "
            "was missed. Make sure every CHECK # line in the document "
            "becomes a withdrawal transaction, not just rows in the main "
            "MISCELLANEOUS DEBITS table."
        )
        lessons.append((_hash(pattern), hint))

    # ---- missed remote deposits ----
    if any("REMOTE DEPOSIT" in d for d in new_descs):
        pattern = "missed_remote_deposit"
        hint = (
            "Past mistake: REMOTE DEPOSIT rows on the same date sometimes "
            "look duplicated but each one is a distinct transaction. Do "
            "not de-dupe by description."
        )
        lessons.append((_hash(pattern), hint))

    # ---- hallucinated rows that the repair removed ----
    removed = desc_before - desc_after
    if any("BEGINNING BALANCE" in d or "ENDING BALANCE" in d for d in removed):
        pattern = "hallucinated_balance_marker"
        hint = (
            "Past mistake: a 'BEGINNING BALANCE' / 'ENDING BALANCE' marker "
            "row was incorrectly emitted as a transaction. These are "
            "section markers, not transactions; skip them."
        )
        lessons.append((_hash(pattern), hint))

    return lessons


class LessonsStore:
    """Append-only persistent store of repair lessons."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def record(self, pattern_hash: str, hint: str, source: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO lessons (pattern_hash, hint, source) "
                    "VALUES (?, ?, ?)",
                    (pattern_hash, hint, source),
                )
            except sqlite3.IntegrityError:
                # Already have this exact lesson -- nothing to do.
                pass

    def top_hints(self, limit: int = 5) -> list[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT hint, helpful_count, unhelpful_count, created_at "
                "FROM lessons "
                "ORDER BY (helpful_count - unhelpful_count) DESC, created_at DESC "
                "LIMIT ?",
                (limit,),
            ).fetchall()
        return [r[0] for r in rows]

    def feedback(self, hint: str, helpful: bool) -> None:
        col = "helpful_count" if helpful else "unhelpful_count"
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE lessons SET {col} = {col} + 1 WHERE hint = ?",
                (hint,),
            )

    def stats(self) -> dict:
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
            helpful = conn.execute(
                "SELECT COALESCE(SUM(helpful_count), 0) FROM lessons"
            ).fetchone()[0]
            unhelpful = conn.execute(
                "SELECT COALESCE(SUM(unhelpful_count), 0) FROM lessons"
            ).fetchone()[0]
        return {"total": total, "helpful": helpful, "unhelpful": unhelpful}


def lessons_block(store: LessonsStore, limit: int = 5) -> str:
    """Render the top-N lessons as an appendable prompt block.

    Returns '' when there are no lessons -- avoids polluting the prompt
    on a fresh deployment.
    """
    hints = store.top_hints(limit)
    if not hints:
        return ""
    lines = [
        "",
        "# Lessons from previous extractions (do not repeat these mistakes)",
    ]
    for i, h in enumerate(hints, 1):
        lines.append(f"{i}. {h}")
    return "\n".join(lines)
