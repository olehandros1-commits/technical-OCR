from __future__ import annotations

import re
from datetime import date, datetime

from dobs.domain.value_objects.raw_row import RawRow

_MONTH = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
_DATE_RE = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"-?\$?\d{1,3}(?:,\d{3})*\.\d{2}\b")

_BALANCE_MARKERS = (
    "BEGINNING BALANCE",
    "ENDING BALANCE",
    "OPENING BALANCE",
    "CLOSING BALANCE",
    "TOTAL DEPOSITS",
    "TOTAL WITHDRAWALS",
    "PRIOR BALANCE",
)

_MONTH_TO_NUM = {
    m: i + 1
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}


class RowParser:
    __slots__ = ()

    def __init__(self, /) -> None:
        pass

    def _parse_amount(self, s: str) -> float:
        return float(s.replace("$", "").replace(",", ""))

    def _to_iso(self, month_abbr: str, day: str, period_start: date) -> str:
        m = _MONTH_TO_NUM.get(month_abbr.title())
        if m is None:
            return ""
        try:
            d = date(period_start.year, m, int(day))
        except ValueError:
            return ""
        if (period_start - d).days > 31:
            try:
                d = date(period_start.year + 1, m, int(day))
            except ValueError:
                pass
        return d.isoformat()

    def _is_balance_marker(self, desc: str) -> bool:
        upper = desc.upper()
        return any(marker in upper for marker in _BALANCE_MARKERS)

    def _is_check_row(self, desc: str) -> bool:
        return bool(re.search(r"\bCHECK\s*#?\s*\*?\d{3,6}\b", desc, re.IGNORECASE))

    def _clean_description(self, s: str) -> str:
        s = re.sub(r"\s+", " ", s).strip(" \t,;|")
        return s

    def parse(self, text: str, period_start_iso: str) -> list[RawRow]:
        try:
            period_start = date.fromisoformat(period_start_iso)
        except (ValueError, TypeError):
            period_start = datetime.now().date()

        matches = list(_DATE_RE.finditer(text))
        rows: list[RawRow] = []
        for i, m in enumerate(matches):
            chunk_start = m.start()
            chunk_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[chunk_start:chunk_end].strip()

            body = chunk[m.end() - m.start() :].strip()

            amts_iter = list(_AMOUNT_RE.finditer(body))
            if not amts_iter:
                continue

            desc = body[: amts_iter[0].start()]
            desc = self._clean_description(desc)

            amount_floats = [self._parse_amount(a.group(0)) for a in amts_iter]

            balance: float | None = None
            tx_amounts: list[float] = amount_floats
            if len(amount_floats) >= 2:
                balance = amount_floats[-1]
                tx_amounts = amount_floats[:-1]

            date_iso = self._to_iso(m.group(1), m.group(2), period_start)
            is_check = self._is_check_row(desc)
            is_marker = self._is_balance_marker(desc)

            confidence = 1.0
            if not date_iso:
                confidence -= 0.5
            if len(amount_floats) > 3:
                confidence -= 0.2

            rows.append(
                RawRow(
                    date_iso=date_iso,
                    description=desc,
                    amounts=tuple(tx_amounts),
                    balance=balance,
                    raw=chunk,
                    confidence=max(0.0, confidence),
                    is_check=is_check,
                    likely_marker=is_marker,
                )
            )

        return rows

    def filter_transactions(self, rows: list[RawRow]) -> list[RawRow]:
        out: list[RawRow] = []
        for r in rows:
            if r.likely_marker:
                continue
            if not r.amounts:
                continue
            if not r.description or len(r.description) < 2:
                continue
            if not r.date_iso:
                continue
            out.append(r)
        return out
