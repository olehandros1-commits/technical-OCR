"""Tests for forensic / anti-fraud rules."""
from datetime import date, timedelta
from extractor.forensic import forensic_anomalies
from extractor.schemas import Transaction


def _t(day: int, amount: float, side: str = "deposit", vendor: str | None = None):
    d = date(2025, 4, 1) + timedelta(days=(day - 1))
    return Transaction(
        date=d.isoformat(),
        description=f"row{day}",
        deposit=amount if side == "deposit" else None,
        withdrawal=amount if side == "withdrawal" else None,
        vendor=vendor,
    )


def test_benford_flag_when_distribution_far_off():
    # Force first digit '9' on 80 rows -- guaranteed Benford violation.
    txns = [_t(d % 28 + 1, 9_000 + d, "deposit") for d in range(80)]
    out = forensic_anomalies(txns)
    msgs = [a.message for a in out]
    assert any("benford" in m for m in msgs), msgs


def test_vendor_concentration_flag():
    txns = [
        _t(1, 80_000, "withdrawal", vendor="Single Vendor"),
        _t(2, 5_000,  "withdrawal", vendor="Other"),
        _t(3, 5_000,  "withdrawal", vendor="Other"),
    ]
    out = forensic_anomalies(txns)
    msgs = [a.message for a in out]
    assert any("vendor_concentration" in m for m in msgs), msgs


def test_velocity_burst():
    # 30 rows on day 1, then 1-2 rows on other days.
    txns = [_t(1, 100 + i, "deposit") for i in range(30)]
    txns += [_t(d, 100, "deposit") for d in range(2, 28)]
    out = forensic_anomalies(txns)
    assert any("velocity" in a.message for a in out)


def test_weekend_flag():
    # 2025-04-05 = Saturday
    saturday = Transaction(date="2025-04-05", description="x", deposit=100.0)
    out = forensic_anomalies([saturday])
    assert any("weekend" in a.message for a in out)


def test_round_number_excess():
    txns = [_t(i + 1, 5000, "withdrawal") for i in range(20)]
    txns += [_t(i + 1, 1234.56, "withdrawal") for i in range(2)]
    out = forensic_anomalies(txns)
    msgs = [a.message for a in out]
    assert any("round_numbers" in m for m in msgs), msgs


def test_no_anomalies_on_empty_input():
    assert forensic_anomalies([]) == []
