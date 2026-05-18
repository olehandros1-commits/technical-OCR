"""LLM-based fallback for segmenting unfamiliar bank layouts.

If the regex-based segmenter ([segment.py]) finds zero "Beginning Balance"
markers, we ask an LLM to locate statement boundaries in the document text
and return a list of (period_start_date, marker_phrase) tuples we can use
to slice the text.

Why a fallback instead of always-LLM:
  * Regex is free and deterministic; for any US bank that uses the standard
    summary block it works.
  * Only unusual layouts (UK, EU, neobanks) need this fallback.
  * The LLM call is one per *document*, not per statement, so it adds
    almost nothing to total cost.
"""
from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole
from extractor.security import safe_wrap


class _Boundary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start_iso: str = Field(
        description="Statement period start date in YYYY-MM-DD format."
    )
    anchor_phrase: str = Field(
        description=(
            "An EXACT substring (10-80 chars) from the document that appears "
            "at the start of this statement -- used to slice the text."
        )
    )


class _BoundariesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    boundaries: list[_Boundary]


_SYSTEM = """You are scanning a multi-statement bank document and listing
where each statement starts.

You will be given the full text of a document that contains one or more bank
statements (possibly from different periods, possibly from different
accounts). Your job is to return one entry per statement with:
  * period_start_iso: the start date of that statement's coverage period,
    in YYYY-MM-DD.
  * anchor_phrase: an EXACT verbatim substring from the document (10-80
    characters) that uniquely identifies the start of that statement.

How to find statement starts:
  * Look for phrases like 'Beginning Balance as of', 'Opening Balance',
    'Statement Period', 'Statement From ... to ...', or any other phrasing
    that marks the start of a new account-period.
  * Each entry should be a distinct statement -- do not include duplicate
    page-header repeats.

Return the boundaries in document order. If no boundaries are found, return
an empty list."""


def llm_find_boundaries(
    text: str,
    backend: LLMBackend,
    *,
    head_chars: int = 60000,
) -> list[tuple[str, str]]:
    """Returns [(period_start_iso, anchor_phrase), ...] from one LLM call.

    To stay within reasonable context, we send only the first `head_chars`
    chars of the document. For very large documents this is a limitation;
    a chunking strategy could be added later.
    """
    body = text[:head_chars]
    wrapped, _ = safe_wrap(body)
    user = (
        "Find every statement-start in the document below and return the "
        "list as a JSON object.\n\n"
        f"{wrapped}"
    )
    resp = backend.call_structured(
        system=_SYSTEM,
        user=user,
        response_model=_BoundariesResponse,
        role=LLMRole.CHEAP,
    )
    return [(b.period_start_iso, b.anchor_phrase) for b in resp.boundaries]
