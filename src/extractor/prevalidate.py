"""Pre-flight cheap check: is this even a bank statement?

Cost on Anthropic Haiku: ~$0.001 per document. Saves you from
accidentally running the expensive extraction pipeline on a receipt,
an invoice, a contract, a screenshot of nothing, or a corrupt PDF
that text-extracted into noise.

If the cheap-tier model says "no, not a bank statement", we fail fast
with `NotABankStatementError` and the caller surfaces a clean rejection
to the user. Bypass with `EXTRACTOR_PREVALIDATE=0`.
"""
from __future__ import annotations
import logging
import os
from pydantic import BaseModel, ConfigDict, Field

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole

log = logging.getLogger(__name__)


class NotABankStatementError(RuntimeError):
    pass


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_bank_statement: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


_SYSTEM = """You are a one-shot document classifier. Decide whether the
text below comes from a BANK STATEMENT (an account-summary document
showing beginning balance, transactions, ending balance for a bank
deposit/checking/savings/credit-card account).

NOT a bank statement: receipts, invoices, contracts, tax forms, KYC
documents, screenshots of unrelated apps, generic text, marketing
materials, blank pages, corrupt OCR output that doesn't parse as words.

Return only the structured verdict. Use is_bank_statement=false with
low confidence on any document you cannot positively identify.
"""


def is_bank_statement(text: str, backend: LLMBackend) -> _Verdict:
    """Cheap-tier verdict. Empty or trivially short text -> hard false."""
    head = text[:4000].strip()
    if len(head) < 200:
        return _Verdict(
            is_bank_statement=False, confidence=1.0,
            reason="document text too short to be a bank statement",
        )
    user = (
        "Classify the following document text. Return ONLY the structured "
        "verdict.\n\n--- DOCUMENT TEXT ---\n" + head + "\n--- END ---"
    )
    return backend.call_structured(
        system=_SYSTEM,
        user=user,
        response_model=_Verdict,
        role=LLMRole.CHEAP,
    )


def assert_bank_statement(text: str, backend: LLMBackend, *,
                          min_confidence: float = 0.6) -> None:
    """Raise NotABankStatementError if the classifier rules it out."""
    if os.getenv("EXTRACTOR_PREVALIDATE", "1") not in {"1", "true", "yes"}:
        return
    verdict = is_bank_statement(text, backend)
    if (not verdict.is_bank_statement) and verdict.confidence >= min_confidence:
        raise NotABankStatementError(
            f"Pre-validation rejected this document: {verdict.reason} "
            f"(confidence {verdict.confidence:.2f})."
        )
