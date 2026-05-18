"""Stage 4: extract all transactions from one statement segment.

Two execution modes:
  * Single-call: one LLM call on the whole segment. Used when the segment
    is small enough that splitting wouldn't pay back the per-call overhead.
  * Chunked + parallel: split the segment into N date-range chunks
    (`chunking.chunk_segment_by_date_ranges`), extract each chunk in
    parallel (same system-prompt cache), then merge + dedupe.

Big statements (~200 transactions) drop from ~120 s to ~25-30 s end-to-end
in chunked mode because the bottleneck is output-tokens-per-call, not
input.
"""
from __future__ import annotations
import concurrent.futures as cf
import logging
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole
from extractor.prompts import TRANSACTIONS_SYSTEM
from extractor.schemas import Transaction, SkippedRow
from extractor.security import safe_wrap
from extractor.chunking import (
    TransactionChunk,
    chunk_segment_by_date_ranges,
    merge_chunks,
)

log = logging.getLogger(__name__)


class TransactionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transactions: list[Transaction]
    skipped_rows: list[SkippedRow] = Field(default_factory=list)


def _augmented_system() -> str:
    """Static system prompt + cached top-N lessons from past repairs.

    The static prefix stays cacheable; the lessons block is short and
    its content drifts slowly, so the cache hit-rate stays high in
    practice.
    """
    try:
        from extractor.pipeline import _lessons_store
        from extractor.prompt_lessons import lessons_block
        return TRANSACTIONS_SYSTEM + lessons_block(_lessons_store(), limit=5)
    except Exception:
        return TRANSACTIONS_SYSTEM


def _single_call(
    segment_text: str,
    period_start: str,
    period_end: str,
    backend: LLMBackend,
    extra_hint: str = "",
) -> TransactionsResponse:
    wrapped, stripped = safe_wrap(segment_text)
    if stripped:
        log.warning("[transactions] prompt-injection patterns stripped: %s", stripped)
    user = (
        f"Statement period: {period_start} to {period_end}\n"
        + (extra_hint + "\n\n" if extra_hint else "")
        + "Extract every transaction from EVERY section (Miscellaneous "
          "Debits & Credits, Checks Paid, etc.) and return as a JSON "
          "object. Skip 'BEGINNING BALANCE' / 'ENDING BALANCE' marker "
          "rows and ignore the DAILY BALANCE SUMMARY block.\n\n"
        + wrapped
    )
    return backend.call_structured(
        system=_augmented_system(),
        user=user,
        response_model=TransactionsResponse,
        role=LLMRole.EXTRACT,
    )


def extract_transactions(
    segment_text: str,
    period_start: str,
    period_end: str,
    backend: LLMBackend,
    *,
    chunk: bool = True,
    n_chunks: int = 4,
    parallel: int = 4,
    use_hybrid: bool | None = None,
) -> TransactionsResponse:
    """Returns a TransactionsResponse for one statement segment.

    Three execution modes:
      * Hybrid (use_hybrid=True): regex pre-parse + thin LLM validator.
        ~5-10x less LLM output. Best for local Ollama and cheap cloud.
      * Chunked LLM (chunk=True, use_hybrid=False): 4 parallel LLM calls,
        one per date range. Cloud-prompt-cache friendly.
      * Single LLM call (chunk=False, use_hybrid=False): one call on
        the whole segment. Used for tests or short statements.

    `use_hybrid=None` auto-decides: hybrid for Ollama (per-token decode
    is slow, so cutting output tokens matters), chunked-LLM for cloud
    (parallel cloud calls hide latency and the cache makes input cheap).
    """
    # Auto: hybrid for any backend where output throughput is the bottleneck.
    if use_hybrid is None:
        use_hybrid = getattr(backend, "name", "") == "ollama"

    if use_hybrid:
        from extractor.extract_transactions_hybrid import extract_transactions_hybrid
        return extract_transactions_hybrid(
            segment_text, period_start, period_end, backend,
        )

    if not chunk:
        return _single_call(segment_text, period_start, period_end, backend)

    chunks = chunk_segment_by_date_ranges(
        segment_text, period_start, period_end, n_chunks=n_chunks,
    )
    if len(chunks) == 1:
        # Small statement: chunker decided one chunk is enough.
        return _single_call(segment_text, period_start, period_end, backend)

    log.info("Chunked transactions extraction: %d chunks", len(chunks))

    def _run(c: TransactionChunk) -> TransactionsResponse:
        return _single_call(
            c.text,
            period_start, period_end, backend,
            extra_hint=c.hint(),
        )

    results: list[TransactionsResponse | None] = [None] * len(chunks)
    workers = max(1, min(parallel, len(chunks)))
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {pool.submit(_run, c): i for i, c in enumerate(chunks)}
        for fut in cf.as_completed(future_to_idx):
            i = future_to_idx[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                log.exception("Chunk %d failed", i)
                results[i] = TransactionsResponse(transactions=[], skipped_rows=[
                    SkippedRow(raw="", reason=f"chunk {i} error: {e}"),
                ])

    merged = merge_chunks(r.transactions for r in results if r is not None)
    skipped = [r for sub in (rr.skipped_rows for rr in results if rr is not None)
               for r in sub]
    return TransactionsResponse(transactions=merged, skipped_rows=skipped)
