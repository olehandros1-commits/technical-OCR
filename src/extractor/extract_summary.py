"""Stage 3: extract the SUMMARY block (account + totals) for one statement."""
from __future__ import annotations
import logging
from pydantic import BaseModel, ConfigDict

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole
from extractor.prompts import SUMMARY_SYSTEM
from extractor.schemas import Account, Summary
from extractor.security import safe_wrap

log = logging.getLogger(__name__)


class SummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: Account
    summary: Summary


def extract_summary(
    segment_text: str,
    backend: LLMBackend,
) -> SummaryResponse:
    """LLM call: extract just the account block + summary totals.

    We pass only the first ~6000 chars -- the summary box is always near the
    top of a statement, so this keeps the call fast and cheap. The text is
    sandwiched in DOCUMENT_TEXT fences with injection-stripping applied
    (see `security.safe_wrap`).
    """
    head = segment_text[:6000]
    wrapped, stripped = safe_wrap(head)
    if stripped:
        log.warning("[summary] prompt-injection patterns stripped: %s", stripped)
    user = (
        "Below is the text of one bank statement (truncated to the summary "
        "area), wrapped in DOCUMENT_TEXT fences. Extract the structured "
        "`account` and `summary` blocks and return them as a JSON object "
        "matching the schema.\n\n"
        f"{wrapped}"
    )
    # Summary box is small and structurally simple -> CHEAP tier
    # (Haiku on Anthropic, qwen2.5:7b on Ollama). 10-12x cheaper than
    # Sonnet and equally accurate on the summary block.
    return backend.call_structured(
        system=SUMMARY_SYSTEM,
        user=user,
        response_model=SummaryResponse,
        role=LLMRole.CHEAP,
    )
