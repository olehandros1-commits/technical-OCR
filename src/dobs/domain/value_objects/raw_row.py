from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True, slots=True)
class RawRow:
    date_iso: str
    description: str
    amounts: tuple[float, ...]
    balance: float | None
    raw: str
    confidence: float = 1.0
    is_check: bool = False
    likely_marker: bool = False
