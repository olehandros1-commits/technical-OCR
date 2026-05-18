"""Detect recurring transactions (subscriptions, payroll, rent).

Why: a flat list of 1,600 transactions is data; a list with 30 of them
tagged "monthly subscription to Acme" is INSIGHT. Finance teams ask
"what are we paying every month" -- that's the question this answers.

Deterministic, no LLM. We look for groups of transactions that share:
  * normalised vendor (or first 30 chars of description if no vendor)
  * same side (deposit / withdrawal)
  * amount within $1.00 of each other
and recur on a predictable cadence (weekly / fortnightly / monthly).

Output is a list of `RecurringGroup` records the UI can render as
"Subscriptions" / "Recurring deposits" panels, distinct from the raw
transactions table.
"""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean, median, pstdev

from extractor.schemas import Transaction


@dataclass
class RecurringGroup:
    """A set of transactions that look like the same recurring payment."""
    vendor_key: str            # normalised string used for grouping
    side: str                  # "deposit" | "withdrawal"
    avg_amount: float
    cadence_days: float        # median gap between consecutive occurrences
    cadence_label: str         # "weekly" | "fortnightly" | "monthly" | "irregular"
    occurrences: list[int] = field(default_factory=list)  # tx indices
    next_predicted_date: str | None = None

    def to_dict(self) -> dict:
        return {
            "vendor_key": self.vendor_key,
            "side": self.side,
            "avg_amount": round(self.avg_amount, 2),
            "cadence_days": round(self.cadence_days, 1),
            "cadence_label": self.cadence_label,
            "count": len(self.occurrences),
            "occurrences": self.occurrences,
            "next_predicted_date": self.next_predicted_date,
        }


_NORMALISE_RE = re.compile(r"[^a-z0-9 ]+")
_DIGIT_RUN_RE = re.compile(r"\b\d{4,}\b")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(desc: str, vendor: str | None) -> str:
    """A grouping key that survives reference-number noise.

    Vendor wins when present (already normalised by the enrich stage).
    Otherwise strip digits-runs (invoice numbers like '1452496195')
    and punctuation so 'PAYABLES 1452496195' and 'PAYABLES 9912841234'
    collapse to the same key.
    """
    if vendor:
        return vendor.strip().lower()[:40]
    raw = desc.lower()
    raw = _DIGIT_RUN_RE.sub("", raw)
    raw = _NORMALISE_RE.sub(" ", raw)
    raw = _WHITESPACE_RE.sub(" ", raw).strip()
    return raw[:40]


def _cadence_label(median_gap: float) -> str:
    if 5 <= median_gap <= 9:    return "weekly"
    if 12 <= median_gap <= 16:  return "fortnightly"
    if 27 <= median_gap <= 33:  return "monthly"
    if 86 <= median_gap <= 95:  return "quarterly"
    return "irregular"


def detect_recurring(
    transactions: list[Transaction],
    *,
    min_occurrences: int = 3,
    amount_tolerance: float = 1.0,
) -> list[RecurringGroup]:
    """Return recurring groups across the given transactions list."""
    by_key: dict[tuple[str, str], list[tuple[int, Transaction]]] = defaultdict(list)
    for idx, t in enumerate(transactions):
        side = "deposit" if t.deposit is not None else "withdrawal"
        key = (_normalise(t.description, t.vendor), side)
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
        # Tighten the cluster: drop items whose amount strays far from the mean.
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
        # Reject "groups" that are just same-day duplicates (gap == 0).
        if med_gap < 2:
            continue
        # Reject high-variance clusters: real subscriptions are regular,
        # so max gap shouldn't be more than 2x the min gap.
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
            cadence_label=_cadence_label(med_gap),
            occurrences=[i for i, _ in cluster],
            next_predicted_date=next_date,
        ))
    # Largest groups first (most signal).
    groups.sort(key=lambda g: (-len(g.occurrences), -g.avg_amount))
    return groups
