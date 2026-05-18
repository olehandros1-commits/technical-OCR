from dobs.domain.services.reconcile import reconcile
from dobs.domain.value_objects.summary import Summary
from dobs.domain.value_objects.transaction import Transaction


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


async def test_perfect_reconciliation():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=1050.0,
        deposits_total=100.0,
        deposits_count=2,
        withdrawals_total=50.0,
        withdrawals_count=1,
    )
    txns = [_t(40.0, "deposit"), _t(60.0, "deposit"), _t(50.0, "withdrawal")]
    r = await reconcile(summary, txns)
    assert r.ok
    assert r.deposits_sum == 100.0
    assert r.withdrawals_sum == 50.0
    assert len(r.issues) == 0


async def test_missing_deposit_detected():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=1100.0,
        deposits_total=100.0,
        deposits_count=2,
        withdrawals_total=0.0,
        withdrawals_count=0,
    )
    txns = [_t(40.0, "deposit")]
    r = await reconcile(summary, txns)
    assert not r.ok
    assert r.deposits_total_delta == 60.0
    assert r.deposits_count_delta == 1
    assert len(r.issues) >= 2


async def test_balance_equation_check():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=999.0,
        deposits_total=100.0,
        deposits_count=1,
        withdrawals_total=50.0,
        withdrawals_count=1,
    )
    txns = [_t(100.0, "deposit"), _t(50.0, "withdrawal")]
    r = await reconcile(summary, txns)
    assert not r.ok
    assert abs(r.balance_equation_delta - (-51.0)) < 0.01


async def test_tolerance_for_rounding():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=1099.999,
        deposits_total=100.0,
        deposits_count=1,
        withdrawals_total=0.0,
        withdrawals_count=0,
    )
    txns = [_t(100.0, "deposit")]
    r = await reconcile(summary, txns)
    assert r.ok


async def test_null_counts_skipped():
    summary = _s(
        beginning_balance=1000.0,
        ending_balance=1100.0,
        deposits_total=100.0,
        deposits_count=None,
        withdrawals_total=0.0,
        withdrawals_count=None,
    )
    r = await reconcile(summary, [_t(100.0, "deposit")])
    assert r.ok
    assert r.deposits_count_delta == 0
