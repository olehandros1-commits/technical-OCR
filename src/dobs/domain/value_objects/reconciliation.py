from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, kw_only=True, slots=True)
class ReconciliationResult:
    ok: bool
    deposits_sum: float
    withdrawals_sum: float
    deposits_count_actual: int
    withdrawals_count_actual: int
    deposits_total_delta: float = 0.0
    withdrawals_total_delta: float = 0.0
    deposits_count_delta: int = 0
    withdrawals_count_delta: int = 0
    balance_equation_delta: float = 0.0
    issues: tuple[str, ...] = field(default_factory=tuple)
