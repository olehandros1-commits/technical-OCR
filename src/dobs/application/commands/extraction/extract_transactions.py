from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from dobs.application.commands.extraction.extract_transactions_hybrid import (
    ExtractTransactionsHybridCommand,
    ExtractTransactionsHybridHandler,
    _TransactionsResult,
)
from dobs.application.ports.lessons_store import LessonsStorePort
from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.application.services.chunking import chunk_segment_by_date_ranges, merge_chunks
from dobs.domain.prompts import TRANSACTIONS_SYSTEM
from dobs.domain.services.prompt_sanitizer import safe_wrap
from dobs.domain.value_objects.llm_role import LLMRole
from dobs.domain.value_objects.skipped_row import SkippedRow
from dobs.domain.value_objects.transaction import Transaction


@dataclass(frozen=True, kw_only=True, slots=True)
class ExtractTransactionsCommand:
    segment_text: str
    period_start: str
    period_end: str
    chunked: bool = True
    use_hybrid: bool | None = None


class ExtractTransactionsHandler:
    def __init__(
        self,
        /,
        *,
        llm: LLMBackendPort,
        hybrid: ExtractTransactionsHybridHandler,
        lessons: LessonsStorePort | None = None,
    ) -> None:
        self._llm = llm
        self._hybrid = hybrid
        self._lessons = lessons

    async def _augmented_system(self) -> str:
        if self._lessons is None:
            return TRANSACTIONS_SYSTEM
        try:
            from dobs.application.services.lessons_helpers import lessons_block
            hints = await self._lessons.top_hints(limit=5)
            return TRANSACTIONS_SYSTEM + lessons_block(hints)
        except Exception:
            return TRANSACTIONS_SYSTEM

    async def _single_call(
        self,
        segment_text: str,
        period_start: str,
        period_end: str,
        extra_hint: str = "",
    ) -> _TransactionsResult:
        system = await self._augmented_system()
        wrapped, _ = safe_wrap(segment_text)
        user = (
            f"Statement period: {period_start} to {period_end}\n"
            + (extra_hint + "\n\n" if extra_hint else "")
            + "Extract every transaction from EVERY section (Miscellaneous "
              "Debits & Credits, Checks Paid, etc.) and return as a JSON "
              "object. Skip 'BEGINNING BALANCE' / 'ENDING BALANCE' marker "
              "rows and ignore the DAILY BALANCE SUMMARY block.\n\n"
            + wrapped
        )
        return await self._llm.call_structured(
            system=system,
            user=user,
            response_model=_TransactionsResult,
            role=LLMRole.EXTRACT,
        )

    async def __call__(self, command: ExtractTransactionsCommand) -> _TransactionsResult:
        use_hybrid = command.use_hybrid
        if use_hybrid is None:
            use_hybrid = getattr(self._llm, "name", "") == "ollama"

        if use_hybrid:
            return await self._hybrid(
                ExtractTransactionsHybridCommand(
                    segment_text=command.segment_text,
                    period_start=command.period_start,
                    period_end=command.period_end,
                )
            )

        if not command.chunked:
            return await self._single_call(
                command.segment_text, command.period_start, command.period_end
            )

        chunks = await asyncio.to_thread(
            chunk_segment_by_date_ranges,
            command.segment_text,
            command.period_start,
            command.period_end,
        )

        if len(chunks) == 1:
            return await self._single_call(
                command.segment_text, command.period_start, command.period_end
            )

        async def _run_chunk(c) -> _TransactionsResult:
            try:
                return await self._single_call(
                    c.text, command.period_start, command.period_end, c.hint()
                )
            except Exception as exc:
                return _TransactionsResult(
                    transactions=[],
                    skipped_rows=[SkippedRow(raw="", reason=f"chunk error: {exc}")],
                )

        results = await asyncio.gather(*(_run_chunk(c) for c in chunks))
        merged = merge_chunks(r.transactions for r in results)
        skipped = [s for r in results for s in r.skipped_rows]
        return _TransactionsResult(transactions=merged, skipped_rows=skipped)
