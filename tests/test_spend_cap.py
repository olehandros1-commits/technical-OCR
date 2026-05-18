import pytest

from dobs.application.errors import SpendCapExceededError
from dobs.application.services.spend_guard import SpendGuard as SpendCap


async def test_default_cap_is_unlimited():
    c = SpendCap()
    warn, breached = await c.record(99999.0)
    assert not warn
    assert not breached


async def test_cap_warns_at_ratio():
    c = SpendCap(cap_usd=10.0, warn_at_ratio=0.5)
    warn, breached = await c.record(6.0)
    assert warn
    assert not breached
    warn2, _ = await c.record(0.5)
    assert not warn2


async def test_cap_breaches_and_raises():
    c = SpendCap(cap_usd=2.0)
    with pytest.raises(SpendCapExceededError):
        await c.record(2.5)
    assert c.spent > 2.0


async def test_remaining_reports_correctly():
    c = SpendCap(cap_usd=5.0)
    await c.record(1.5)
    assert c.remaining() == pytest.approx(3.5)
