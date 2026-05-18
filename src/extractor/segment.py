"""Stage 2: Segment a multi-statement document into individual statement texts.

A bank statement always begins with a "Balance Summary" block containing
"Beginning Balance as of <date>" and ends just before the next statement's
opening, or at end of document. The OCR text often duplicates header fragments
on each page; we dedupe segments that share the same (period_start, account)
key and prefer the longest variant.
"""
from __future__ import annotations
import re
from dataclasses import dataclass


# Pattern tolerates a stray space inside the dollar amount (OCR artefact).
_BEGINNING_BAL_RE = re.compile(
    r"Beginning Balance as of\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_ENDING_BAL_RE = re.compile(
    r"Ending Balance as of\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
# Try several places the account number can appear.
_ACCOUNT_RE = re.compile(
    r"Account Number[:\s]+X*\s*([0-9]{4,16})",
    re.IGNORECASE,
)


@dataclass
class StatementSegment:
    """A slice of document text representing one statement."""
    text: str
    period_start_raw: str  # e.g. "04/01/2025"
    period_end_raw: str | None
    account_hint: str | None  # best-guess last 4 found in segment

    @property
    def key(self) -> tuple[str, str | None]:
        return (self.period_start_raw, self.account_hint)


def _account_hint(text: str) -> str | None:
    """Best-effort grab the account last4 from segment text.

    Heuristic: look at the first ~3000 chars (header area), find the longest
    digit run on an "Account Number" line and keep the last 4.
    """
    head = text[:3000]
    candidates: list[str] = []
    for m in _ACCOUNT_RE.finditer(head):
        digits = m.group(1)
        if len(digits) >= 4:
            candidates.append(digits[-4:])
    if not candidates:
        return None
    # Prefer the most common -- guards against single OCR misread.
    from collections import Counter

    return Counter(candidates).most_common(1)[0][0]


def split_statements(text: str) -> list[StatementSegment]:
    """Split full document text into one segment per statement.

    Algorithm: find each 'Beginning Balance as of' marker, slice text between
    consecutive markers, then dedupe duplicate segments (caused by repeated
    header blocks on each printed page).

    If no markers are found, callers should fall back to
    `split_statements_llm` for unknown bank layouts.
    """
    matches = list(_BEGINNING_BAL_RE.finditer(text))
    if not matches:
        return []

    segments: list[StatementSegment] = []
    for i, m in enumerate(matches):
        start = max(0, m.start() - 800)  # include preceding header (bank, account)
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
                account_hint=_account_hint(chunk),
            )
        )

    # Dedup logic. The OCR text often contains two representations of the
    # same statement: a flowing-text version (rich, has all transactions and
    # the full account header) and a table-extracted version (sparse, has
    # only the balance summary block). The table version typically has
    # account_hint=None because there is no "Account Number:" line near it.
    #
    # Rule: group by period_start_raw.
    #   - If the group contains ANY real (non-None) account_hint, drop all
    #     entries whose account_hint is None.
    #   - Then dedupe duplicates with identical (period, account) by keeping
    #     the longest text.
    #   - Different real accounts in the same period are kept separately
    #     (e.g. September 2024 has both account 4664 and 4623).
    from collections import defaultdict

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

    # Re-sort in document order using start position of the kept variant.
    kept.sort(key=lambda s: text.find(s.text[:200]))

    # Skip empty segments: a "Beginning Balance as of" marker can appear
    # inside a continuation page of the previous statement (Azure DI
    # repeats the summary block when a section spans pages). If a segment
    # has near-zero transaction-like rows AND a real prior segment for
    # the same account-period already exists, drop it -- the LLM call
    # would just waste tokens on a balance summary table.
    return [s for s in kept if _looks_like_real_statement(s.text)]


def _looks_like_real_statement(text: str) -> bool:
    """Cheap sanity check: real statements have at least a handful of
    date-prefixed amount lines. Empty / re-emitted summary blocks have 0.
    """
    import re
    # Same liberal date+amount pattern the row parser uses.
    pat = re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
        r"\d{1,2}\b[^\n]{0,200}\d{1,3}(?:,\d{3})*\.\d{2}",
        re.IGNORECASE,
    )
    return len(pat.findall(text)) >= 5


def split_statements_llm(text: str, backend) -> list[StatementSegment]:
    """LLM-driven fallback: ask the model where statements start.

    Used when split_statements() returns []. Builds segments using anchor
    phrases the LLM returns; the rest of the pipeline is unchanged.
    """
    from extractor.segment_llm import llm_find_boundaries

    boundaries = llm_find_boundaries(text, backend)
    if not boundaries:
        return []

    positions: list[tuple[int, str, str]] = []
    for period_iso, anchor in boundaries:
        idx = text.find(anchor)
        if idx == -1:
            continue
        # Normalise the period to MM/DD/YYYY so the rest of the pipeline
        # sees the same shape as the regex path.
        from datetime import date
        try:
            d = date.fromisoformat(period_iso)
            period_raw = d.strftime("%m/%d/%Y")
        except ValueError:
            period_raw = period_iso
        positions.append((idx, period_raw, anchor))

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
                account_hint=_account_hint(chunk),
            )
        )
    return segments
