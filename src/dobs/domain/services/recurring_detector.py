from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median

from dobs.domain.value_objects.recurring_group import RecurringGroup
from dobs.domain.value_objects.transaction import Transaction


_NORMALISE_RE = re.compile(r"[^a-z0-9 ]+")
_DIGIT_RUN_RE = re.compile(r"\b\d{4,}\b")
_WHITESPACE_RE = re.compile(r"\s+")


class RecurringDetector:
    __slots__ = ()

    def __init__(self, /) -> None:
        pass

    def _normalise(self, desc: str, vendor: str | None) -> str:
        if vendor:
            return vendor.strip().lower()[:40]
        raw = desc.lower()
        raw = _DIGIT_RUN_RE.sub("", raw)
        raw = _NORMALISE_RE.sub(" ", raw)
        raw = _WHITESPACE_RE.sub(" ", raw).strip()
        return raw[:40]

    def _cadence_label(self, median_gap: float) -> str:
        if 5 <= median_gap <= 9:
            return "weekly"
        if 12 <= median_gap <= 16:
            return "fortnightly"
        if 27 <= median_gap <= 33:
            return "monthly"
        if 86 <= median_gap <= 95:
            return "quarterly"
        return "irregular"

    async def detect(
        self,
        transactions: list[Transaction],
        *,
        min_occurrences: int = 3,
        amount_tolerance: float = 1.0,
    ) -> list[RecurringGroup]:
        by_key: dict[tuple[str, str], list[tuple[int, Transaction]]] = defaultdict(list)
        for idx, t in enumerate(transactions):
            side = "deposit" if t.deposit is not None else "withdrawal"
            key = (self._normalise(t.description, t.vendor), side)
            by_key[key].append((idx, t))

        groups: list[RecurringGroup] = []
        for (vendor_key, side), items in by_key.items():
            if len(items) < min_occurrences:
                continue
            amounts = [(it[1].deposit if side == "deposit" else it[1].withdrawal) or 0.0
                       for it in items]
            if not amounts:
                continue
            avg_amt = mean(amounts)
            cluster = [
                (i, t) for i, t in items
                if abs(((t.deposit if side == "deposit" else t.withdrawal) or 0) - avg_amt)
                   <= max(amount_tolerance, avg_amt * 0.05)
            ]
            if len(cluster) < min_occurrences:
                continue
            dates: list[date] = []
            for _, t in cluster:
                try:
                    dates.append(date.fromisoformat(t.date))
                except ValueError:
                    pass
            dates.sort()
            if len(dates) < min_occurrences:
                continue
            gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
            if not gaps:
                continue
            med_gap = median(gaps)
            if med_gap < 2:
                continue
            if min(gaps) > 0 and max(gaps) / min(gaps) > 4:
                continue
            amts = [(it[1].deposit if side == "deposit" else it[1].withdrawal) or 0
                    for it in cluster]
            next_date = (dates[-1] + timedelta(days=int(round(med_gap)))).isoformat()
            groups.append(RecurringGroup(
                vendor_key=vendor_key,
                side=side,
                avg_amount=mean(amts),
                cadence_days=med_gap,
                cadence_label=self._cadence_label(med_gap),
                occurrences=tuple(i for i, _ in cluster),
                next_predicted_date=next_date,
            ))
        groups.sort(key=lambda g: (-len(g.occurrences), -g.avg_amount))
        return groups
