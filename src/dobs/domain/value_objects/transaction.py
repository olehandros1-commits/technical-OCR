from __future__ import annotations

from dataclasses import dataclass

from dobs.domain.value_objects.tx_category import TxCategory


@dataclass(frozen=True, kw_only=True, slots=True)
class Transaction:
    date: str
    description: str
    deposit: float | None = None
    withdrawal: float | None = None
    category: TxCategory | None = None
    vendor: str | None = None
    confidence: float | None = None
    vendor_logo: str | None = None
    vendor_domain: str | None = None
    vendor_canonical: str | None = None
