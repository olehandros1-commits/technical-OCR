"""Unit tests for the deterministic reconcile stage.

We don't mock the LLM here -- those are integration tests that need the API
key. These tests cover the math that is the heart of the verification stage.
"""
from extractor.reconcile import reconcile
from extractor.schemas import Summary, Transaction


def _s(**kw):
    base = dict(
        beginning_balance=100.0,
        ending_balance=100.0,
        deposits_total=0.0,
        deposits_count=0,
        withdrawals_total=0.0,
        withdrawals_count=0,
    )
    base.update(kw)
    return Summary(**base)


def _t(amount: float, side: str = "deposit") -> Transaction:
    if side == "deposit":
        return Transaction(date="2025-04-01", description="x", deposit=amount)
    return Transaction(date="2025-04-01", description="x", withdrawal=amount)


def test_perfect_reconciliation():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=1050.0,
        deposits_total=100.0,
        deposits_count=2,
        withdrawals_total=50.0,
        withdrawals_count=1,
    )
    txns = [_t(40.0, "deposit"), _t(60.0, "deposit"), _t(50.0, "withdrawal")]
    r = reconcile(summary, txns)
    assert r.ok
    assert r.deposits_sum == 100.0
    assert r.withdrawals_sum == 50.0
    assert r.issues == []


def test_missing_deposit_detected():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=1100.0,
        deposits_total=100.0,
        deposits_count=2,
        withdrawals_total=0.0,
        withdrawals_count=0,
    )
    txns = [_t(40.0, "deposit")]  # missed one
    r = reconcile(summary, txns)
    assert not r.ok
    assert r.deposits_total_delta == 60.0  # missing $60
    assert r.deposits_count_delta == 1
    assert len(r.issues) >= 2


def test_balance_equation_check():
    # Sums match per-side but beginning + dep - with != ending.
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=999.0,  # off by $51
        deposits_total=100.0,
        deposits_count=1,
        withdrawals_total=50.0,
        withdrawals_count=1,
    )
    txns = [_t(100.0, "deposit"), _t(50.0, "withdrawal")]
    r = reconcile(summary, txns)
    assert not r.ok
    assert abs(r.balance_equation_delta - (-51.0)) < 0.01


def test_tolerance_for_rounding():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=1099.999,
        deposits_total=100.0,
        deposits_count=1,
        withdrawals_total=0.0,
        withdrawals_count=0,
    )
    txns = [_t(100.0, "deposit")]
    r = reconcile(summary, txns)
    # Within $0.01 tolerance.
    assert r.ok


def test_null_counts_skipped():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=1100.0,
        deposits_total=100.0,
        deposits_count=None,
        withdrawals_total=0.0,
        withdrawals_count=None,
    )
    r = reconcile(summary, [_t(100.0, "deposit")])
    assert r.ok
    assert r.deposits_count_delta == 0
