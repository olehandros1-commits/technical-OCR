from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.services.prompt_sanitizer import PromptSanitizer
from dobs.domain.value_objects.llm_role import LLMRole

_BEGINNING_BAL_RE = re.compile(
    r"Beginning Balance as of\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_ENDING_BAL_RE = re.compile(
    r"Ending Balance as of\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_ACCOUNT_RE = re.compile(
    r"Account Number[:\s]+X*\s*([0-9]{4,16})",
    re.IGNORECASE,
)


@dataclass
class StatementSegment:
    text: str
    period_start_raw: str
    period_end_raw: str | None
    account_hint: str | None

    @property
    def key(self) -> tuple[str, str | None]:
        return (self.period_start_raw, self.account_hint)


class StatementSegmenter:
    __slots__ = ("_sanitizer",)

    def __init__(self, /, *, sanitizer: PromptSanitizer | None = None) -> None:
        self._sanitizer = sanitizer or PromptSanitizer()

    def _account_hint(self, text: str) -> str | None:
        head = text[:3000]
        candidates: list[str] = []
        for m in _ACCOUNT_RE.finditer(head):
            digits = m.group(1)
            if len(digits) >= 4:
                candidates.append(digits[-4:])
        if not candidates:
            return None
        return Counter(candidates).most_common(1)[0][0]

    def _looks_like_real_statement(self, text: str) -> bool:
        pat = re.compile(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
            r"\d{1,2}\b[^\n]{0,200}\d{1,3}(?:,\d{3})*\.\d{2}",
            re.IGNORECASE,
        )
        return len(pat.findall(text)) >= 5

    async def split(self, text: str) -> list[StatementSegment]:
        matches = list(_BEGINNING_BAL_RE.finditer(text))
        if not matches:
            return []

        segments: list[StatementSegment] = []
        for i, m in enumerate(matches):
            start = max(0, m.start() - 800)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[start:end]
            period_start_raw = m.group(1)
            end_m = _ENDING_BAL_RE.search(chunk)
            period_end_raw = end_m.group(1) if end_m else None
            segments.append(
                StatementSegment(
                    text=chunk,
                    period_start_raw=period_start_raw,
                    period_end_raw=period_end_raw,
                    account_hint=self._account_hint(chunk),
                )
            )

        by_period: dict[str, list[StatementSegment]] = defaultdict(list)
        for seg in segments:
            by_period[seg.period_start_raw].append(seg)

        kept: list[StatementSegment] = []
        for _period, group in by_period.items():
            has_real_account = any(s.account_hint is not None for s in group)
            if has_real_account:
                group = [s for s in group if s.account_hint is not None]
            best_by_account: dict[str | None, StatementSegment] = {}
            for seg in group:
                key = seg.account_hint
                if key not in best_by_account or len(seg.text) > len(best_by_account[key].text):
                    best_by_account[key] = seg
            kept.extend(best_by_account.values())

        kept.sort(key=lambda s: text.find(s.text[:200]))
        return [s for s in kept if self._looks_like_real_statement(s.text)]

    async def split_with_llm(self, text: str, llm: LLMBackendPort) -> list[StatementSegment]:
        from pydantic import BaseModel, ConfigDict, Field

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

Return the boundaries in document order. If no boundaries are found, return
an empty list."""

        body = text[:60000]
        wrapped, _ = self._sanitizer.safe_wrap(body)
        user = (
            "Find every statement-start in the document below and return the "
            "list as a JSON object.\n\n"
            f"{wrapped}"
        )
        resp = await llm.call_structured(
            system=_SYSTEM,
            user=user,
            response_model=_BoundariesResponse,
            role=LLMRole.CHEAP,
        )

        positions: list[tuple[int, str, str]] = []
        for b in resp.boundaries:
            idx = text.find(b.anchor_phrase)
            if idx == -1:
                continue
            try:
                d = date.fromisoformat(b.period_start_iso)
                period_raw = d.strftime("%m/%d/%Y")
            except ValueError:
                period_raw = b.period_start_iso
            positions.append((idx, period_raw, b.anchor_phrase))

        positions.sort()
        segments: list[StatementSegment] = []
        for i, (idx, period_raw, _anchor) in enumerate(positions):
            start = max(0, idx - 800)
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            chunk = text[start:end]
            end_m = _ENDING_BAL_RE.search(chunk)
            segments.append(
                StatementSegment(
                    text=chunk,
                    period_start_raw=period_raw,
                    period_end_raw=end_m.group(1) if end_m else None,
                    account_hint=self._account_hint(chunk),
                )
            )
        return segments
