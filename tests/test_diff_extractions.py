"""Tests for diff_extractions."""
from extractor.diff_extractions import diff_extractions


def _stmt(transactions, summary=None):
    return {
        "account": {"period": {"start": "2025-04-01", "end": "2025-04-30"},
                    "account_last4": "4664"},
        "summary": summary or {
            "beginning_balance": 100, "ending_balance": 200,
            "deposits_total": 100, "deposits_count": 1,
            "withdrawals_total": 0,  "withdrawals_count": 0,
        },
        "transactions": transactions,
    }


def test_identical_extractions_yield_zero_diffs():
    a = _stmt([{"date": "2025-04-01", "description": "X", "deposit": 100,
                "withdrawal": None}])
    b = _stmt([{"date": "2025-04-01", "description": "X", "deposit": 100,
                "withdrawal": None}])
    d = diff_extractions(a, b)
    assert d.only_in_a_count == 0
    assert d.only_in_b_count == 0
    assert d.changed_count == 0
    assert d.common_count == 1


def test_added_and_removed_rows():
    a = _stmt([{"date": "2025-04-01", "description": "X", "deposit": 100,
                "withdrawal": None}])
    b = _stmt([{"date": "2025-04-02", "description": "Y", "deposit": 200,
                "withdrawal": None}])
    d = diff_extractions(a, b)
    assert d.only_in_a_count == 1
    assert d.only_in_b_count == 1
    assert d.common_count == 0


def test_soft_field_changes_detected():
    base = {"date": "2025-04-01", "description": "X", "deposit": 100,
            "withdrawal": None}
    a = _stmt([{**base, "category": None, "confidence": None}])
    b = _stmt([{**base, "category": "PAYROLL", "confidence": 0.9}])
    d = diff_extractions(a, b)
    assert d.common_count == 1
    assert d.changed_count == 1
    assert "category" in d.changed[0]["fields"]


def test_summary_deltas_reported():
    a = _stmt([], summary={
        "beginning_balance": 100, "ending_balance": 200,
        "deposits_total": 100, "deposits_count": 1,
        "withdrawals_total": 0, "withdrawals_count": 0,
    })
    b = _stmt([], summary={
        "beginning_balance": 100, "ending_balance": 250,
        "deposits_total": 150, "deposits_count": 2,
        "withdrawals_total": 0, "withdrawals_count": 0,
    })
    d = diff_extractions(a, b)
    assert "ending_balance" in d.summary_deltas
    assert d.summary_deltas["ending_balance"]["delta"] == 50
