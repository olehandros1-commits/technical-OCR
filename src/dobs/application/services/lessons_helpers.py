from __future__ import annotations

import hashlib

from dobs.domain.value_objects.reconciliation import ReconciliationResult
from dobs.domain.value_objects.transaction import Transaction


class LessonsHelper:
    __slots__ = ()

    def __init__(self, /) -> None:
        pass

    def _hash(self, s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]

    def diagnose_repair(
        self,
        before: ReconciliationResult,
        after: ReconciliationResult,
        prev_txns: list[Transaction],
        fixed_txns: list[Transaction],
    ) -> list[tuple[str, str]]:
        lessons: list[tuple[str, str]] = []
        if not before or before.ok or not after.ok:
            return lessons

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
            lessons.append((self._hash(pattern), hint))

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
            lessons.append((self._hash(pattern), hint))

        if any("REMOTE DEPOSIT" in d for d in new_descs):
            pattern = "missed_remote_deposit"
            hint = (
                "Past mistake: REMOTE DEPOSIT rows on the same date sometimes "
                "look duplicated but each one is a distinct transaction. Do "
                "not de-dupe by description."
            )
            lessons.append((self._hash(pattern), hint))

        removed = desc_before - desc_after
        if any("BEGINNING BALANCE" in d or "ENDING BALANCE" in d for d in removed):
            pattern = "hallucinated_balance_marker"
            hint = (
                "Past mistake: a 'BEGINNING BALANCE' / 'ENDING BALANCE' marker "
                "row was incorrectly emitted as a transaction. These are "
                "section markers, not transactions; skip them."
            )
            lessons.append((self._hash(pattern), hint))

        return lessons

    def build_prompt_block(self, hints: list[str]) -> str:
        if not hints:
            return ""
        lines = [
            "",
            "# Lessons from previous extractions (do not repeat these mistakes)",
        ]
        for i, h in enumerate(hints, 1):
            lines.append(f"{i}. {h}")
        return "\n".join(lines)
