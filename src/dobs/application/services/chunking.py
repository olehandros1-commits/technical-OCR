from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from dobs.domain.value_objects.transaction import Transaction


_DATE_LINE_RE = re.compile(
    r"\b("
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
    r")\s+(\d{1,2})(?=\s+[A-Z#])",
    re.IGNORECASE,
)

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


class TransactionChunker:
    __slots__ = ()

    def __init__(self, /) -> None:
        pass

    def _month_to_num(self, abbr: str) -> int:
        return {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }[abbr.title()]

    def _date_line_positions(self, text: str, year: int) -> list[tuple[int, date]]:
        out: list[tuple[int, date]] = []
        for m in _DATE_LINE_RE.finditer(text):
            try:
                month = self._month_to_num(m.group(1))
                day = int(m.group(2))
                d = date(year, month, day)
            except (ValueError, KeyError):
                continue
            out.append((m.start(1), d))
        return out

    def _trim_tail(self, text: str) -> tuple[str, str]:
        latest = len(text)
        for marker in _TAIL_MARKERS:
            idx = text.rfind(marker)
            if idx > 0 and idx < latest:
                latest = idx
        return text[:latest], text[latest:]

    def chunk_by_date_ranges(
        self,
        segment_text: str,
        period_start_iso: str,
        period_end_iso: str,
        *,
        n_chunks: int = 4,
        min_transactions_to_chunk: int = 80,
    ) -> list[TransactionChunk]:
        try:
            year = datetime.fromisoformat(period_start_iso).year
        except ValueError:
            year = datetime.now().year

        body, tail = self._trim_tail(segment_text)
        positions = self._date_line_positions(body, year)

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
            return [TransactionChunk(
                text=segment_text,
                date_range_start=p_start,
                date_range_end=p_end,
                chunk_index=0,
                total_chunks=1,
            )]

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
            if i < n_chunks - 1:
                chunk_end = boundaries[i + 1] - timedelta(days=1)
            else:
                chunk_end = boundaries[i + 1]
            if i < n_chunks - 1:
                cut_off = next(
                    (off for off, d in positions if d >= boundaries[i + 1]),
                    len(body),
                )
            else:
                cut_off = len(body)
            start_off = next(
                (off for off, d in positions if d >= chunk_start),
                0,
            )
            header = segment_text[:min(800, start_off)]
            body_slice = body[start_off:cut_off]
            body_slice += tail if i == n_chunks - 1 else ""
            chunks.append(TransactionChunk(
                text=header + "\n\n" + body_slice,
                date_range_start=chunk_start,
                date_range_end=chunk_end,
                chunk_index=i,
                total_chunks=n_chunks,
            ))
        return chunks

    def merge(self, chunked_results: Iterable[list[Transaction]]) -> list[Transaction]:
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
