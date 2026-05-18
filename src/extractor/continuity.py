"""Cross-statement continuity audit.

Given the list of statements produced by `extract_all`, group them into
chains by (account_last4) and verify that each statement's ending balance
matches the next statement's beginning balance within $0.01.

Finance teams call this "bank statement continuity" -- breaking it usually
means a missing month, a missing transaction, or a fabricated total.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass
class ContinuityIssue:
    account_last4: str | None
    prev_period: str
    next_period: str
    expected_beginning: float
    actual_beginning: float
    delta: float

    def to_dict(self) -> dict:
        return {
            "account_last4": self.account_last4,
            "prev_period": self.prev_period,
            "next_period": self.next_period,
            "expected_beginning": self.expected_beginning,
            "actual_beginning": self.actual_beginning,
            "delta": round(self.delta, 2),
            "message": (
                f"Account {self.account_last4}: ending of {self.prev_period} "
                f"is ${self.expected_beginning:,.2f} but next statement "
                f"({self.next_period}) begins at ${self.actual_beginning:,.2f} "
                f"(delta ${self.delta:+,.2f})."
            ),
        }


def _parse_iso(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def audit_continuity(results: list[dict], tolerance: float = 0.01) -> list[ContinuityIssue]:
    """Group statements per account, sort by period start, check continuity."""
    by_account: dict[str | None, list[dict]] = defaultdict(list)
    for r in results:
        by_account[r["account"].get("account_last4")].append(r)

    issues: list[ContinuityIssue] = []
    for acct, group in by_account.items():
        # Sort by period start (chronological).
        group_sorted = sorted(
            group,
            key=lambda r: _parse_iso(r["account"]["period"]["start"]) or date.min,
        )
        for prev, nxt in zip(group_sorted, group_sorted[1:]):
            prev_end_date = _parse_iso(prev["account"]["period"]["end"])
            next_start_date = _parse_iso(nxt["account"]["period"]["start"])
            # Skip if the two statements are not consecutive (e.g. user only
            # uploaded some months; we don't want false alarms for gaps).
            if (prev_end_date and next_start_date
                    and (next_start_date - prev_end_date).days > 5):
                continue
            expected = prev["summary"]["ending_balance"]
            actual = nxt["summary"]["beginning_balance"]
            delta = round(actual - expected, 2)
            if abs(delta) > tolerance:
                issues.append(ContinuityIssue(
                    account_last4=acct,
                    prev_period=prev["account"]["period"]["start"],
                    next_period=nxt["account"]["period"]["start"],
                    expected_beginning=expected,
                    actual_beginning=actual,
                    delta=delta,
                ))
    return issues
