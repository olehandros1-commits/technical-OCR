from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.services.prompt_sanitizer import PromptSanitizer
from dobs.domain.services.row_parser import RawRow, RowParser
from dobs.domain.value_objects.llm_role import LLMRole
from dobs.domain.value_objects.skipped_row import SkippedRow
from dobs.domain.value_objects.transaction import Transaction


_VALIDATOR_SYSTEM = """You are validating pre-extracted bank statement
transactions. A regex parser has already pulled candidate rows from the
OCR text. Your job is to:

  1. For each row, decide if the amount is a DEPOSIT or a WITHDRAWAL.
     Use the description + (when present) the second amount column or
     the running balance trend.
  2. Skip rows that are NOT real transactions (section markers, totals,
     headers that slipped past the regex).
  3. If two consecutive rows clearly belong to the same wrapped
     transaction (rare), MERGE them by skipping the second and folding
     its description into the first.
  4. CHECK # rows are always WITHDRAWALS. Use description "CHECK #NNNNN".

Rules:
  * Never invent rows; only emit rows whose `index` appears in the input.
  * Keep the original `description`; only minor cleanup is fine.
  * `deposit` / `withdrawal`: exactly one is the amount, the other null.
  * The input rows already have ISO dates and stripped amounts; reuse them.
"""


class _ValidatedRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    keep: bool
    side: str = Field(pattern="^(deposit|withdrawal)$")
    date: str
    description: str
    amount: float


class _ValidatorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[_ValidatedRow]


class _TransactionsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transactions: list[Transaction]
    skipped_rows: list[SkippedRow] = Field(default_factory=list)


def _records_for_llm(rows: list[RawRow]) -> list[dict]:
    out: list[dict] = []
    for i, r in enumerate(rows):
        out.append({
            "index": i,
            "date": r.date_iso,
            "desc": r.description[:120],
            "amounts": [round(a, 2) for a in r.amounts],
            "balance": round(r.balance, 2) if r.balance is not None else None,
            "is_check": r.is_check,
        })
    return out


@dataclass(frozen=True, kw_only=True, slots=True)
class ExtractTransactionsHybridCommand:
    segment_text: str
    period_start: str
    period_end: str


class ExtractTransactionsHybridHandler:
    def __init__(
        self,
        /,
        *,
        llm: LLMBackendPort,
        sanitizer: PromptSanitizer,
        row_parser: RowParser,
    ) -> None:
        self._llm = llm
        self._sanitizer = sanitizer
        self._row_parser = row_parser

    async def _single_call(
        self,
        segment_text: str,
        period_start: str,
        period_end: str,
        extra_hint: str = "",
    ) -> _TransactionsResult:
        from dobs.domain.prompts import TRANSACTIONS_SYSTEM
        wrapped, _ = self._sanitizer.safe_wrap(segment_text)
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
            system=TRANSACTIONS_SYSTEM,
            user=user,
            response_model=_TransactionsResult,
            role=LLMRole.EXTRACT,
        )

    async def __call__(
        self,
        command: ExtractTransactionsHybridCommand,
    ) -> _TransactionsResult:
        raw_rows = await asyncio.to_thread(
            self._row_parser.parse, command.segment_text, command.period_start
        )
        candidates = await asyncio.to_thread(self._row_parser.filter_transactions, raw_rows)

        if not candidates:
            return await self._single_call(
                command.segment_text, command.period_start, command.period_end
            )

        records = _records_for_llm(candidates)
        user = (
            f"Statement period: {command.period_start} to {command.period_end}\n"
            f"Validate these {len(records)} pre-extracted rows. For each, "
            "decide deposit vs withdrawal, drop non-transactions, and merge "
            "obvious wraps. Return one ValidatedRow per kept input row.\n\n"
            f"{json.dumps(records, indent=1)}"
        )

        try:
            resp = await self._llm.call_structured(
                system=_VALIDATOR_SYSTEM,
                user=user,
                response_model=_ValidatorResponse,
                role=LLMRole.CHEAP,
            )
        except Exception:
            return await self._single_call(
                command.segment_text, command.period_start, command.period_end
            )

        transactions: list[Transaction] = []
        skipped: list[SkippedRow] = []
        for v in resp.rows:
            if not v.keep:
                if 0 <= v.index < len(candidates):
                    skipped.append(SkippedRow(
                        raw=candidates[v.index].raw,
                        reason=f"validator dropped row {v.index}",
                    ))
                continue
            amount = round(v.amount, 2)
            deposit = amount if v.side == "deposit" else None
            withdrawal = amount if v.side == "withdrawal" else None
            transactions.append(Transaction(
                date=v.date,
                description=v.description,
                deposit=deposit,
                withdrawal=withdrawal,
            ))
        return _TransactionsResult(transactions=transactions, skipped_rows=skipped)
