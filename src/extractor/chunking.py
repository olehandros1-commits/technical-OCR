"""Split one statement into N parallel-extractable chunks.

Why: extracting 200 transactions in one LLM call serialises ~10 K output
tokens (~80-120 seconds on Sonnet). Splitting into 4 chunks that share the
same system-prompt cache pulls that down to ~25-30 seconds end-to-end,
because all 4 calls run in parallel and each generates ~2.5 K output.

Strategy: chunk by DATE RANGE, not by character offset. We:
  1. Find all "<MonthAbbr> <Day>" line starts in the segment.
  2. Split those date positions into N roughly-equal date ranges.
  3. Slice the text from the first date-line of one range to the first
     date-line of the next.
  4. Each chunk is passed to the same extract_transactions prompt with an
     explicit date-range hint ("only extract transactions dated X..Y").

Edge cases handled:
  * Small statements (< THRESHOLD transactions): no chunking, single call.
  * Daily Balance Summary section: kept attached to the LAST chunk so the
    "do not extract balance summary" rule applies once, not per chunk.
  * Wrapped descriptions that span multiple lines: the chunk boundaries
    fall on date-line starts, never inside a transaction.
  * Cross-chunk duplicates: caller dedupes by (date, side, amount,
    description) in `merge_chunks`.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from extractor.schemas import Transaction


# Matches a transaction-opening date marker: "Apr 01 AIRLINEHYD..." or
# "Apr 01 CHECK #40788". Requires the date to be followed by something
# that looks like the start of a transaction description (uppercase letter,
# digit, or # so check rows like "CHECK #40788" match). The
# `$<digits>` lookahead is excluded so we don't mistake the BEGINNING
# BALANCE marker line "Apr 01 BEGINNING BALANCE $597,068.70" for the
# anchor we want (we want the next row that has an actual amount column).
#
# We do NOT require a newline before the month token because Azure-DI OCR
# emits flowing text with each "page" as one giant line.
_DATE_LINE_RE = re.compile(
    r"\b("
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
    r")\s+(\d{1,2})(?=\s+[A-Z#])",
    re.IGNORECASE,
)

# Sections we want to keep attached to the LAST chunk so each chunk doesn't
# have to repeat "ignore the daily balance summary". We match on LAST
# occurrence so OCR page-numbers and other early appearances don't
# accidentally trim the body.
_TAIL_MARKERS = ("DAILY BALANCE SUMMARY",)


@dataclass
class TransactionChunk:
    text: str
    date_range_start: date
    date_range_end: date
    chunk_index: int
    total_chunks: int

    def hint(self) -> str:
        return (
            f"Extract only transactions whose date falls within "
            f"{self.date_range_start.isoformat()} to "
            f"{self.date_range_end.isoformat()} (inclusive). Ignore any "
            f"rows outside that range -- those will be extracted by other "
            f"chunks (chunk {self.chunk_index + 1} of {self.total_chunks})."
        )


def _month_to_num(abbr: str) -> int:
    return {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    }[abbr.title()]


def _date_line_positions(text: str, year: int) -> list[tuple[int, date]]:
    """Find every (offset, parsed-date) for date-line starts."""
    out: list[tuple[int, date]] = []
    for m in _DATE_LINE_RE.finditer(text):
        try:
            month = _month_to_num(m.group(1))
            day = int(m.group(2))
            d = date(year, month, day)
        except (ValueError, KeyError):
            continue
        # Use the position of the month abbrev (skip the leading newline/ws).
        out.append((m.start(1), d))
    return out


def _trim_tail(text: str) -> tuple[str, str]:
    """Detach footer / DAILY BALANCE SUMMARY block. Returns (body, tail).

    Uses the LAST occurrence of each marker (not the first) so OCR page-
    numbers or metadata that happens to contain a marker string near the
    top of the document doesn't truncate the body.
    """
    latest = len(text)
    for marker in _TAIL_MARKERS:
        idx = text.rfind(marker)
        if idx > 0 and idx < latest:
            latest = idx
    return text[:latest], text[latest:]


def chunk_segment_by_date_ranges(
    segment_text: str,
    period_start_iso: str,
    period_end_iso: str,
    *,
    n_chunks: int = 4,
    min_transactions_to_chunk: int = 80,
) -> list[TransactionChunk]:
    """Split a statement segment into N chunks aligned on date lines.

    Returns a single-element list (no chunking) when the segment has fewer
    than `min_transactions_to_chunk` candidate date lines, since the
    chunking overhead is not worth it for small statements.
    """
    try:
        year = datetime.fromisoformat(period_start_iso).year
    except ValueError:
        year = datetime.now().year

    body, tail = _trim_tail(segment_text)
    positions = _date_line_positions(body, year)

    # Year rollover: if period spans Dec -> Jan, push Jan dates forward a year.
    p_start = date.fromisoformat(period_start_iso)
    p_end = date.fromisoformat(period_end_iso)
    rolled: list[tuple[int, date]] = []
    for off, d in positions:
        d2 = d
        if d < p_start and (p_end - p_start).days > 0:
            try:
                d2 = date(d.year + 1, d.month, d.day)
            except ValueError:
                pass
        rolled.append((off, d2))
    positions = rolled

    if len(positions) < min_transactions_to_chunk:
        # Not worth chunking; one chunk for the whole segment.
        return [TransactionChunk(
            text=segment_text,
            date_range_start=p_start,
            date_range_end=p_end,
            chunk_index=0,
            total_chunks=1,
        )]

    # Pick boundaries by splitting unique dates into N roughly-equal groups.
    unique_dates = sorted({d for _, d in positions})
    if len(unique_dates) < n_chunks:
        n_chunks = max(1, len(unique_dates))

    boundaries: list[date] = []
    for i in range(n_chunks + 1):
        idx = min(len(unique_dates) - 1, (i * len(unique_dates)) // n_chunks)
        boundaries.append(unique_dates[idx])

    chunks: list[TransactionChunk] = []
    for i in range(n_chunks):
        chunk_start = boundaries[i]
        # Non-overlapping date ranges: intermediate chunks end the day
        # before the next chunk starts. Last chunk gets inclusive end.
        if i < n_chunks - 1:
            chunk_end = boundaries[i + 1] - timedelta(days=1)
        else:
            chunk_end = boundaries[i + 1]
        # Intermediate chunks stop BEFORE the next chunk's first date.
        if i < n_chunks - 1:
            # Find offset of first date-line whose date >= boundaries[i+1].
            cut_off = next(
                (off for off, d in positions if d >= boundaries[i + 1]),
                len(body),
            )
        else:
            cut_off = len(body)
        # Find this chunk's starting offset (first date-line whose date >= chunk_start).
        start_off = next(
            (off for off, d in positions if d >= chunk_start),
            0,
        )
        # Always keep the segment header (first ~800 chars) for context so
        # every chunk sees the bank / account / period.
        header = segment_text[: min(800, start_off)]
        body_slice = body[start_off:cut_off]
        # Attach the tail to the LAST chunk only.
        body_slice += tail if i == n_chunks - 1 else ""
        chunks.append(TransactionChunk(
            text=header + "\n\n" + body_slice,
            date_range_start=chunk_start,
            date_range_end=chunk_end,
            chunk_index=i,
            total_chunks=n_chunks,
        ))
    return chunks


def merge_chunks(chunked_results: Iterable[list[Transaction]]) -> list[Transaction]:
    """Dedup-aware merge.

    Two transactions are considered the same row if they match on
    (date, side, amount, normalised-description). The first one wins.
    This catches accidental cross-chunk duplicates when a description wraps
    onto a line that the next chunk's regex thought was a date-start.
    """
    seen: set[tuple[str, str, float, str]] = set()
    out: list[Transaction] = []
    for chunk in chunked_results:
        for t in chunk:
            side = "D" if t.deposit is not None else "W"
            amount = t.deposit if t.deposit is not None else (t.withdrawal or 0.0)
            key = (t.date, side, round(amount, 2),
                   re.sub(r"\s+", " ", t.description.strip())[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
    return out
