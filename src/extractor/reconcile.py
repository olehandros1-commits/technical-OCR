"""Stage 5: deterministic reconciliation.

We do NOT ask an LLM to judge whether totals add up -- we compute it
ourselves. Two checks:
  1. Per-side sum + count match the printed totals (tolerance $0.01).
  2. The balance equation balances:
        beginning + sum(deposits) - sum(withdrawals) == ending
"""
from __future__ import annotations
from extractor.schemas import (
    Summary,
    Transaction,
    ReconciliationResult,
)

TOLERANCE = 0.01


def _r(x: float) -> float:
    return round(x, 2)


def reconcile(summary: Summary, transactions: list[Transaction]) -> ReconciliationResult:
    deps = [t.deposit for t in transactions if t.deposit is not None]
    withs = [t.withdrawal for t in transactions if t.withdrawal is not None]
    dep_sum = _r(sum(deps))
    with_sum = _r(sum(withs))

    issues: list[str] = []

    dep_total_delta = _r(summary.deposits_total - dep_sum)
    with_total_delta = _r(summary.withdrawals_total - with_sum)

    if abs(dep_total_delta) > TOLERANCE:
        issues.append(
            f"deposits sum mismatch: extracted {dep_sum:.2f}, "
            f"declared {summary.deposits_total:.2f}, delta {dep_total_delta:+.2f}"
        )
    if abs(with_total_delta) > TOLERANCE:
        issues.append(
            f"withdrawals sum mismatch: extracted {with_sum:.2f}, "
            f"declared {summary.withdrawals_total:.2f}, delta {with_total_delta:+.2f}"
        )

    dep_count_delta = 0
    with_count_delta = 0
    if summary.deposits_count is not None:
        dep_count_delta = summary.deposits_count - len(deps)
        if dep_count_delta != 0:
            issues.append(
                f"deposits count mismatch: extracted {len(deps)}, "
                f"declared {summary.deposits_count}, delta {dep_count_delta:+d}"
            )
    if summary.withdrawals_count is not None:
        with_count_delta = summary.withdrawals_count - len(withs)
        if with_count_delta != 0:
            issues.append(
                f"withdrawals count mismatch: extracted {len(withs)}, "
                f"declared {summary.withdrawals_count}, delta {with_count_delta:+d}"
            )

    # Balance equation: beginning + Σdep - Σwith should equal ending.
    derived_ending = _r(summary.beginning_balance + dep_sum - with_sum)
    balance_delta = _r(summary.ending_balance - derived_ending)
    if abs(balance_delta) > TOLERANCE:
        issues.append(
            f"balance equation mismatch: beginning {summary.beginning_balance:.2f} "
            f"+ deposits {dep_sum:.2f} - withdrawals {with_sum:.2f} = "
            f"{derived_ending:.2f}, but ending is {summary.ending_balance:.2f} "
            f"(delta {balance_delta:+.2f})"
        )

    return ReconciliationResult(
        ok=not issues,
        deposits_sum=dep_sum,
        withdrawals_sum=with_sum,
        deposits_count_actual=len(deps),
        withdrawals_count_actual=len(withs),
        deposits_total_delta=dep_total_delta,
        withdrawals_total_delta=with_total_delta,
        deposits_count_delta=dep_count_delta,
        withdrawals_count_delta=with_count_delta,
        balance_equation_delta=balance_delta,
        issues=issues,
    )
