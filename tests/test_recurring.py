"""Tests for the recurring-transaction detector."""
from datetime import date, timedelta

from extractor.recurring import detect_recurring, _normalise, _cadence_label
from extractor.schemas import Transaction


def _tx(d: str, desc: str, amount: float, side: str = "withdrawal", vendor=None) -> Transaction:
    t = Transaction(
        date=d, description=desc,
        deposit=amount if side == "deposit" else None,
        withdrawal=amount if side == "withdrawal" else None,
        vendor=vendor,
    )
    return t


def test_monthly_subscription_detected():
    txns = [
        _tx("2025-01-15", "AWS SUBSCRIPTION", 199.00, "withdrawal", "AWS"),
        _tx("2025-02-15", "AWS SUBSCRIPTION", 199.00, "withdrawal", "AWS"),
        _tx("2025-03-15", "AWS SUBSCRIPTION", 199.00, "withdrawal", "AWS"),
        _tx("2025-04-15", "AWS SUBSCRIPTION", 199.00, "withdrawal", "AWS"),
    ]
    groups = detect_recurring(txns, min_occurrences=3)
    assert len(groups) == 1
    g = groups[0]
    assert g.cadence_label == "monthly"
    assert g.avg_amount == 199.0
    assert g.next_predicted_date.startswith("2025-05")


def test_weekly_payroll_detected():
    base = date(2025, 1, 6)  # Monday
    txns = [
        _tx((base + timedelta(weeks=i)).isoformat(),
            "PAYROLL ACME CORP", 5000.0, "deposit", "Acme")
        for i in range(6)
    ]
    groups = detect_recurring(txns)
    assert len(groups) == 1
    assert groups[0].cadence_label == "weekly"
    assert groups[0].side == "deposit"


def test_one_off_transactions_not_grouped():
    txns = [
        _tx("2025-01-15", "ACME", 100, "withdrawal"),
        _tx("2025-02-01", "OTHER", 50, "withdrawal"),
    ]
    assert detect_recurring(txns) == []


def test_amount_tolerance():
    # +/-$1 wobble is OK for "same subscription".
    txns = [
        _tx(f"2025-{m:02d}-15", "SAAS", 99.99, vendor="SaaS")
        for m in range(1, 5)
    ]
    txns[1] = _tx("2025-02-15", "SAAS", 100.50, vendor="SaaS")  # slight bump
    groups = detect_recurring(txns)
    assert len(groups) == 1
    assert groups[0].cadence_label == "monthly"


def test_normalise_strips_reference_numbers():
    a = _normalise("PAYABLES 1452496195", None)
    b = _normalise("PAYABLES 9912841234", None)
    assert a == b


def test_high_variance_cluster_dropped():
    # Random gaps -> not regular -> not a subscription
    dates = ["2025-01-01", "2025-01-05", "2025-02-20", "2025-04-01"]
    txns = [_tx(d, "RANDOM", 50.0, vendor="X") for d in dates]
    assert detect_recurring(txns) == []


def test_cadence_label_buckets():
    assert _cadence_label(7) == "weekly"
    assert _cadence_label(14) == "fortnightly"
    assert _cadence_label(30) == "monthly"
    assert _cadence_label(90) == "quarterly"
    assert _cadence_label(45) == "irregular"
