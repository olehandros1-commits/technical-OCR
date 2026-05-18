from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True, slots=True)
class Summary:
    beginning_balance: float
    ending_balance: float
    deposits_total: float
    withdrawals_total: float
    deposits_count: int | None = None
    withdrawals_count: int | None = None
    currency: str | None = None
