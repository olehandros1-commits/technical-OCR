from __future__ import annotations

from dataclasses import dataclass

from dobs.domain.value_objects.period import Period


@dataclass(frozen=True, kw_only=True, slots=True)
class Account:
    bank: str
    account_last4: str | None
    period: Period
