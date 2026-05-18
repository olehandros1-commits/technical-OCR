from __future__ import annotations

import json
import time
from dataclasses import dataclass

from dobs.application.commands.extraction.extract_transactions_hybrid import _TransactionsResult
from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.prompts import REPAIR_SYSTEM
from dobs.domain.services.prompt_sanitizer import PromptSanitizer
from dobs.domain.services.reconcile import Reconciler
from dobs.domain.value_objects.llm_role import LLMRole
from dobs.domain.value_objects.reconciliation import ReconciliationResult
from dobs.domain.value_objects.summary import Summary
from dobs.domain.value_objects.transaction import Transaction
from dobs.main.logging_setup import get_logger

log = get_logger(__name__)


def _total_error(recon: ReconciliationResult) -> float:
    return (
        abs(recon.deposits_total_delta)
        + abs(recon.withdrawals_total_delta)
        + abs(recon.balance_equation_delta)
        + abs(recon.deposits_count_delta) * 100
        + abs(recon.withdrawals_count_delta) * 100
    )


def _build_repair_user(
    segment_text: str,
    period_start: str,
    period_end: str,
    summary: Summary,
    prev_transactions: list[Transaction],
    recon: ReconciliationResult,
    sanitizer: PromptSanitizer,
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
        f"{json.dumps([{'date': t.date, 'description': t.description, 'deposit': t.deposit, 'withdrawal': t.withdrawal} for t in prev_transactions], indent=2)}\n\n"
        "# Full statement text (wrapped in DOCUMENT_TEXT fences)\n"
        f"{sanitizer.safe_wrap(segment_text)[0]}\n\n"
        "Return the FULL CORRECTED transactions list as a JSON object."
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class RepairStatementCommand:
    segment_text: str
    summary: Summary
    transactions: list[Transaction]
    reconciliation: ReconciliationResult
    period_start: str
    period_end: str


class RepairStatementHandler:
    def __init__(
        self,
        /,
        *,
        llm: LLMBackendPort,
        sanitizer: PromptSanitizer,
        reconciler: Reconciler,
    ) -> None:
        self._llm = llm
        self._sanitizer = sanitizer
        self._reconciler = reconciler

    async def _repair_once(
        self,
        segment_text: str,
        period_start: str,
        period_end: str,
        summary: Summary,
        prev_transactions: list[Transaction],
        recon: ReconciliationResult,
    ) -> _TransactionsResult:
        user = _build_repair_user(
            segment_text,
            period_start,
            period_end,
            summary,
            prev_transactions,
            recon,
            self._sanitizer,
        )
        return await self._llm.call_structured(
            system=REPAIR_SYSTEM,
            user=user,
            response_model=_TransactionsResult,
            role=LLMRole.REPAIR,
        )

    async def __call__(
        self,
        command: RepairStatementCommand,
    ) -> tuple[list[Transaction], list[ReconciliationResult]]:
        max_attempts = 4
        wall_clock_budget_s = 600.0
        min_progress_ratio = 0.5

        history: list[ReconciliationResult] = [command.reconciliation]
        current = list(command.transactions)
        recon = command.reconciliation
        best_error = _total_error(recon)
        best_transactions = current

        deadline = time.monotonic() + wall_clock_budget_s

        for attempt in range(1, max_attempts + 1):
            if recon.ok:
                break
            if time.monotonic() >= deadline:
                break

            try:
                resp = await self._repair_once(
                    command.segment_text,
                    command.period_start,
                    command.period_end,
                    command.summary,
                    current,
                    recon,
                )
                current = list(resp.transactions)
            except Exception:
                log.warning("repair LLM call failed; returning best-so-far", exc_info=True)
                break

            recon = await self._reconciler.reconcile(command.summary, current)
            history.append(recon)
            new_error = _total_error(recon)

            if new_error < best_error - 0.001:
                best_transactions = current
                best_error = new_error
            else:
                break

            prior_error_value = _total_error(history[-2])
            if prior_error_value > 0 and best_error / prior_error_value > (1 - min_progress_ratio):
                if attempt >= max_attempts - 1:
                    break

        return best_transactions, history
