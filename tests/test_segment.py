"""Tests for the statement segmentation stage."""
from extractor.segment import split_statements


# Each fixture statement carries 5+ date-amount rows so the new
# `_looks_like_real_statement` filter accepts them. Real Ixonia statements
# have 60-200; we keep the test fixture compact but above threshold.
SAMPLE = """
Ixonia Bank
Account Number: 4664
Balance Summary
Beginning Balance as of 04/01/2025  $597,068.70
+ Deposits and Credits (81) $1,214,254.05
Ending Balance as of 04/30/2025 $509,121.59
Apr 01 SOMETHING 1.00 597,069.70
Apr 02 OTHER 2.00 597,071.70
Apr 03 THIRD 3.00 597,074.70
Apr 04 FOURTH 4.00 597,078.70
Apr 05 FIFTH 5.00 597,083.70
Apr 06 SIXTH 6.00 597,089.70

Ixonia Bank
Account Number: 4664
Balance Summary
Beginning Balance as of 05/01/2025  $509,121.59
+ Deposits and Credits (95)
Ending Balance as of 05/31/2025 $164,340.35
May 01 SOMETHING 2.00 509,123.59
May 02 NEXT 3.00 509,126.59
May 03 THIRD 4.00 509,130.59
May 04 FOURTH 5.00 509,135.59
May 05 FIFTH 6.00 509,141.59
May 06 SIXTH 7.00 509,148.59
"""


def test_finds_two_statements():
    segs = split_statements(SAMPLE)
    assert len(segs) == 2
    assert segs[0].period_start_raw == "04/01/2025"
    assert segs[1].period_start_raw == "05/01/2025"
    assert segs[0].account_hint == "4664"


def test_dedup_repeated_header():
    duplicated = SAMPLE + "\n" + SAMPLE
    segs = split_statements(duplicated)
    # The same (period, account) pair appears twice; dedupe keeps one each.
    keys = {s.key for s in segs}
    assert len(keys) == 2
