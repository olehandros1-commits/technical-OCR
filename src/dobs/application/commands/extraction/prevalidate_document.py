from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dobs.application.errors import NotABankStatementError
from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.value_objects.llm_role import LLMRole


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


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_bank_statement: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


@dataclass(frozen=True, kw_only=True, slots=True)
class PrevalidateDocumentCommand:
    text: str
    min_confidence: float = 0.6


class PrevalidateDocumentHandler:
    def __init__(
        self,
        /,
        *,
        llm: LLMBackendPort,
    ) -> None:
        self._llm = llm

    async def __call__(self, command: PrevalidateDocumentCommand) -> None:
        head = command.text[:4000].strip()
        if len(head) < 200:
            raise NotABankStatementError(
                "Document text too short to be a bank statement"
            )
        user = (
            "Classify the following document text. Return ONLY the structured "
            "verdict.\n\n--- DOCUMENT TEXT ---\n" + head + "\n--- END ---"
        )
        verdict = await self._llm.call_structured(
            system=_SYSTEM,
            user=user,
            response_model=_Verdict,
            role=LLMRole.CHEAP,
        )
        if (not verdict.is_bank_statement) and verdict.confidence >= command.min_confidence:
            raise NotABankStatementError(
                f"Pre-validation rejected this document: {verdict.reason} "
                f"(confidence {verdict.confidence:.2f})."
            )
