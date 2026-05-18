"""Tests for the cross-statement continuity audit."""
from extractor.continuity import audit_continuity


def _stmt(start: str, end: str, beginning: float, ending: float,
          last4: str = "4664") -> dict:
    return {
        "account": {
            "bank": "Test Bank",
            "account_last4": last4,
            "period": {"start": start, "end": end},
        },
        "summary": {
            "beginning_balance": beginning,
            "ending_balance": ending,
            "deposits_total": 0, "deposits_count": 0,
            "withdrawals_total": 0, "withdrawals_count": 0,
        },
        "transactions": [],
    }


def test_clean_chain_passes():
    s1 = _stmt("2025-01-01", "2025-01-31", 1000.0, 1500.0)
    s2 = _stmt("2025-02-01", "2025-02-28", 1500.0, 1700.0)
    s3 = _stmt("2025-03-01", "2025-03-31", 1700.0, 2000.0)
    issues = audit_continuity([s1, s2, s3])
    assert issues == []


def test_break_detected():
    s1 = _stmt("2025-01-01", "2025-01-31", 1000.0, 1500.0)
    s2 = _stmt("2025-02-01", "2025-02-28", 1450.0, 1700.0)  # $50 missing
    issues = audit_continuity([s1, s2])
    assert len(issues) == 1
    assert abs(issues[0].delta + 50.0) < 0.01
    assert issues[0].account_last4 == "4664"


def test_different_accounts_dont_interfere():
    a = _stmt("2025-01-01", "2025-01-31", 1000.0, 1500.0, last4="0001")
    b = _stmt("2025-01-01", "2025-01-31", 50.0, 250.0, last4="0002")
    issues = audit_continuity([a, b])
    assert issues == []


def test_gap_in_chain_is_skipped():
    # 6 months between -> we don't try to audit a gap user didn't upload.
    s1 = _stmt("2025-01-01", "2025-01-31", 1000.0, 1500.0)
    s2 = _stmt("2025-07-01", "2025-07-31", 99.0, 250.0)
    issues = audit_continuity([s1, s2])
    assert issues == []
