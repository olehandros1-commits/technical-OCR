"""Hybrid transactions extraction: deterministic regex + thin LLM validator.

Pipeline:
  1. `parse_rows.parse_rows(text)` lifts candidate rows from the OCR text
     using a generic US-bank regex. This is bank-agnostic and runs in
     milliseconds.
  2. Drop balance markers and obvious junk via
     `parse_rows.filter_transaction_rows`.
  3. Send a COMPACT list of pre-parsed rows to the LLM. The model only
     decides deposit-vs-withdrawal (and corrects obvious mistakes); it
     does NOT have to re-read the whole statement.
  4. Output a TransactionsResponse identical to the pure-LLM path so the
     downstream reconciliation / repair / enrich stages don't care which
     path produced the rows.

When the LLM call fails or the regex finds nothing, we fall back to the
pure-LLM path (`extract_transactions._single_call`) so accuracy never
regresses on unseen layouts.

Speedup vs pure LLM (measured on Ixonia Apr 2025, 192 transactions):
  * Pure LLM (chunked, Sonnet):   ~25-30 s, ~10K output tokens
  * Pure LLM (chunked, qwen 14b): ~5 min, throttled by token gen
  * Hybrid (Sonnet validator):    ~5-8 s, ~1K output tokens
  * Hybrid (qwen 14b validator):  ~30-60 s, ~1K output tokens

Same final shape, ~5-10x less LLM output to generate.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole
from extractor.schemas import Transaction, SkippedRow
from extractor.parse_rows import RawRow, parse_rows, filter_transaction_rows
from extractor.extract_transactions import TransactionsResponse, _single_call

log = logging.getLogger(__name__)


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
    date: str   # YYYY-MM-DD
    description: str
    amount: float


class _ValidatorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[_ValidatedRow]


def _records_for_llm(rows: list[RawRow]) -> list[dict]:
    """Minimal JSON the LLM sees: tiny per-row tokens."""
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


def extract_transactions_hybrid(
    segment_text: str,
    period_start: str,
    period_end: str,
    backend: LLMBackend,
    *,
    fallback_on_empty: bool = True,
) -> TransactionsResponse:
    """Returns a TransactionsResponse using regex pre-parse + LLM validator.

    On regex-empty (unfamiliar layout) or LLM error, falls back to the
    pure-LLM extractor so unseen banks still work.
    """
    raw_rows = parse_rows(segment_text, period_start)
    candidates = filter_transaction_rows(raw_rows)
    log.info("hybrid: regex pulled %d candidate rows (of %d raw matches)",
             len(candidates), len(raw_rows))

    if not candidates:
        if not fallback_on_empty:
            return TransactionsResponse(transactions=[])
        log.info("hybrid: regex found 0 rows -> falling back to pure-LLM path")
        return _single_call(segment_text, period_start, period_end, backend)

    records = _records_for_llm(candidates)
    user = (
        f"Statement period: {period_start} to {period_end}\n"
        f"Validate these {len(records)} pre-extracted rows. For each, "
        "decide deposit vs withdrawal, drop non-transactions, and merge "
        "obvious wraps. Return one ValidatedRow per kept input row.\n\n"
        f"{json.dumps(records, indent=1)}"
    )

    try:
        resp = backend.call_structured(
            system=_VALIDATOR_SYSTEM,
            user=user,
            response_model=_ValidatorResponse,
            # CHEAP tier: this is a tagging task, Haiku / qwen 7b is plenty.
            role=LLMRole.CHEAP,
        )
    except Exception as e:
        log.warning("hybrid validator failed (%s) -> pure-LLM fallback", e)
        return _single_call(segment_text, period_start, period_end, backend)

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
    return TransactionsResponse(transactions=transactions, skipped_rows=skipped)
