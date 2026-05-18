"""Tests for the spend cap."""
import pytest

from extractor.spend_cap import SpendCap, SpendCapExceededError


def test_default_cap_is_unlimited():
    c = SpendCap()
    warn, breached = c.record(99999.0)
    assert not warn
    assert not breached


def test_cap_warns_at_ratio():
    c = SpendCap(cap_usd=10.0)
    c.warn_at_ratio = 0.5
    warn, breached = c.record(6.0)
    assert warn
    assert not breached
    # second call after warn shouldn't re-warn
    warn2, _ = c.record(0.5)
    assert not warn2


def test_cap_breaches_and_raises():
    c = SpendCap(cap_usd=2.0)
    with pytest.raises(SpendCapExceededError):
        c.record(2.5)
    # Even after raising, spent reflects the breach attempt.
    assert c.spent > 2.0


def test_remaining_reports_correctly():
    c = SpendCap(cap_usd=5.0)
    c.record(1.5)
    assert c.remaining() == pytest.approx(3.5)
