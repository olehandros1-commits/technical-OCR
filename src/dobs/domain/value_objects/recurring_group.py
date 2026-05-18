from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, kw_only=True, slots=True)
class RecurringGroup:
    vendor_key: str
    side: str
    avg_amount: float
    cadence_days: float
    cadence_label: str
    occurrences: tuple[int, ...] = field(default_factory=tuple)
    next_predicted_date: str | None = None
