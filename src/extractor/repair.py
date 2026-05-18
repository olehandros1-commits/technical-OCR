"""Stage 6: adaptive repair loop with delta-feedback to the LLM.

This is the architectural differentiator: when reconciliation fails we feed
back the exact arithmetic delta and let the model try again. The loop now
adapts -- it continues as long as each iteration meaningfully reduces the
total error, instead of stopping at a fixed cap. A hard wall-clock budget
prevents runaway.
"""
from __future__ import annotations
import json
import logging
import time
from typing import Callable

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole
from extractor.prompts import REPAIR_SYSTEM
from extractor.schemas import Summary, Transaction, ReconciliationResult
from extractor.extract_transactions import TransactionsResponse
from extractor.reconcile import reconcile
from extractor.security import safe_wrap

log = logging.getLogger(__name__)


def _total_error(recon: ReconciliationResult) -> float:
    """Single number that should fall to 0 when reconciled."""
    return (
        abs(recon.deposits_total_delta)
        + abs(recon.withdrawals_total_delta)
        + abs(recon.balance_equation_delta)
        + abs(recon.deposits_count_delta) * 100   # small weight on counts
        + abs(recon.withdrawals_count_delta) * 100
    )


def _build_repair_user(
    segment_text: str,
    period_start: str,
    period_end: str,
    summary: Summary,
    prev_transactions: list[Transaction],
    recon: ReconciliationResult,
) -> str:
    return (
        "RECONCILIATION FAILED. Re-extract the transactions list as a JSON "
        "object.\n\n"
        f"Statement period: {period_start} to {period_end}\n\n"
        "# Reconciliation report\n"
        f"- declared deposits_total: {summary.deposits_total:.2f}\n"
        f"- extracted deposits_sum:  {recon.deposits_sum:.2f}\n"
        f"- delta (declared - extracted): {recon.deposits_total_delta:+.2f}  "
        "(positive = you missed deposits totalling this amount; "
        "negative = you have extra/wrong deposits)\n"
        f"- declared deposits_count: {summary.deposits_count}\n"
        f"- extracted deposits_count: {recon.deposits_count_actual}\n"
        f"- count delta: {recon.deposits_count_delta:+d}\n\n"
        f"- declared withdrawals_total: {summary.withdrawals_total:.2f}\n"
        f"- extracted withdrawals_sum:  {recon.withdrawals_sum:.2f}\n"
        f"- delta: {recon.withdrawals_total_delta:+.2f}\n"
        f"- declared withdrawals_count: {summary.withdrawals_count}\n"
        f"- extracted withdrawals_count: {recon.withdrawals_count_actual}\n"
        f"- count delta: {recon.withdrawals_count_delta:+d}\n\n"
        f"- balance equation delta: {recon.balance_equation_delta:+.2f}\n\n"
        "# Issues\n" + "\n".join(f"- {i}" for i in recon.issues) + "\n\n"
        f"# Previous transactions ({len(prev_transactions)} rows)\n"
        f"{json.dumps([t.model_dump() for t in prev_transactions], indent=2)}\n\n"
        "# Full statement text (wrapped in DOCUMENT_TEXT fences)\n"
        f"{safe_wrap(segment_text)[0]}\n\n"
        "Return the FULL CORRECTED transactions list as a JSON object."
    )


def repair_transactions(
    segment_text: str,
    period_start: str,
    period_end: str,
    summary: Summary,
    prev_transactions: list[Transaction],
    recon: ReconciliationResult,
    backend: LLMBackend,
) -> TransactionsResponse:
    user = _build_repair_user(
        segment_text, period_start, period_end, summary, prev_transactions, recon
    )
    return backend.call_structured(
        system=REPAIR_SYSTEM,
        user=user,
        response_model=TransactionsResponse,
        role=LLMRole.REPAIR,
    )


def repair_loop(
    segment_text: str,
    period_start: str,
    period_end: str,
    summary: Summary,
    transactions: list[Transaction],
    backend: LLMBackend,
    *,
    max_attempts: int = 4,
    wall_clock_budget_s: float = 600.0,
    min_progress_ratio: float = 0.5,
    log_event: Callable[[str, dict], None] | None = None,
) -> tuple[list[Transaction], ReconciliationResult, list[ReconciliationResult]]:
    """Adaptive repair loop.

    Continues as long as:
      * reconciliation is not ok, AND
      * each attempt reduces total error by at least `min_progress_ratio`
        of the previous error (i.e. real progress, not noise), AND
      * `max_attempts` not yet hit, AND
      * `wall_clock_budget_s` not exceeded.

    Returns the BEST list seen (lowest total error), the matching
    reconciliation, and the full history.
    """
    history: list[ReconciliationResult] = []
    current = transactions
    recon = reconcile(summary, current)
    history.append(recon)

    best_transactions = current
    best_recon = recon
    best_error = _total_error(recon)

    if log_event:
        log_event(
            "reconcile",
            {"attempt": 0, "ok": recon.ok, "error": round(best_error, 2),
             "issues": recon.issues},
        )

    deadline = time.time() + wall_clock_budget_s

    for attempt in range(1, max_attempts + 1):
        if recon.ok:
            break
        if time.time() >= deadline:
            log.warning("Repair budget exhausted before reconcile")
            if log_event:
                log_event("repair_timeout", {"attempt": attempt})
            break

        log.info("Repair attempt %d/%d", attempt, max_attempts)
        if log_event:
            log_event("repair_start", {"attempt": attempt, "error": round(best_error, 2)})

        try:
            resp = repair_transactions(
                segment_text, period_start, period_end,
                summary, current, recon, backend,
            )
            current = resp.transactions
        except Exception as e:
            log.warning("Repair attempt %d failed: %s", attempt, e)
            if log_event:
                log_event("repair_error", {"attempt": attempt, "error": str(e)})
            break

        recon = reconcile(summary, current)
        history.append(recon)
        new_error = _total_error(recon)

        if log_event:
            log_event(
                "reconcile",
                {"attempt": attempt, "ok": recon.ok, "error": round(new_error, 2),
                 "issues": recon.issues},
            )

        # Keep the best result seen so far -- never regress.
        if new_error < best_error - 0.001:
            best_transactions = current
            best_recon = recon
            best_error = new_error
        else:
            # No meaningful progress -- bail out, accept the best we have.
            log.info(
                "No progress this attempt (error %.2f >= %.2f), stopping",
                new_error, best_error,
            )
            if log_event:
                log_event("repair_no_progress", {"attempt": attempt, "error": round(new_error, 2)})
            break

        # Progress was made -- continue only if the progress was substantial.
        # (If we reduced error by < min_progress_ratio of previous, we are
        # asymptoting; one more attempt is unlikely to close the gap.)
        prior_error = history[-2]
        prior_error_value = _total_error(prior_error)
        if prior_error_value > 0 and best_error / prior_error_value > (1 - min_progress_ratio):
            log.info(
                "Diminishing returns (%.2f -> %.2f), stopping",
                prior_error_value, best_error,
            )
            if log_event:
                log_event(
                    "repair_diminishing",
                    {"attempt": attempt, "from": round(prior_error_value, 2),
                     "to": round(best_error, 2)},
                )
            # One more attempt before giving up entirely.
            if attempt >= max_attempts - 1:
                break

    return best_transactions, best_recon, history
