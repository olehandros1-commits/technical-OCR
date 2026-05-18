from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from dobs.domain.entities.statement import Statement


@dataclass(frozen=True, kw_only=True, slots=True)
class ContinuityIssue:
    account_last4: str | None
    prev_period: str
    next_period: str
    expected_beginning: float
    actual_beginning: float
    delta: float


class ContinuityAuditor:
    __slots__ = ()

    def __init__(self, /) -> None:
        pass

    def _parse_iso(self, s: str) -> date | None:
        try:
            return date.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    async def audit(
        self,
        statements: list[Statement],
        tolerance: float = 0.01,
    ) -> list[ContinuityIssue]:
        by_account: dict[str | None, list[Statement]] = defaultdict(list)
        for s in statements:
            by_account[s.account.account_last4].append(s)

        issues: list[ContinuityIssue] = []
        for _acct, group in by_account.items():
            group_sorted = sorted(
                group,
                key=lambda s: self._parse_iso(s.account.period.start) or date.min,
            )
            for prev, nxt in zip(group_sorted, group_sorted[1:]):
                prev_end_date = self._parse_iso(prev.account.period.end)
                next_start_date = self._parse_iso(nxt.account.period.start)
                if (prev_end_date and next_start_date
                        and (next_start_date - prev_end_date).days > 5):
                    continue
                expected = prev.summary.ending_balance
                actual = nxt.summary.beginning_balance
                delta = round(actual - expected, 2)
                if abs(delta) > tolerance:
                    issues.append(ContinuityIssue(
                        account_last4=prev.account.account_last4,
                        prev_period=prev.account.period.start,
                        next_period=nxt.account.period.start,
                        expected_beginning=expected,
                        actual_beginning=actual,
                        delta=delta,
                    ))
        return issues
