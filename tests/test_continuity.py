import uuid

from dobs.domain.services.continuity_auditor import ContinuityAuditor

_auditor = ContinuityAuditor()


async def audit_continuity(*args, **kwargs):
    return await _auditor.audit(*args, **kwargs)
from dobs.domain.entities.statement import Statement
from dobs.domain.value_objects.account import Account
from dobs.domain.value_objects.period import Period
from dobs.domain.value_objects.summary import Summary


def _stmt(start: str, end: str, beginning: float, ending: float,
          last4: str = "4664") -> Statement:
    return Statement(
        oid=str(uuid.uuid4()),
        account=Account(
            bank="Test Bank",
            account_last4=last4,
            period=Period(start=start, end=end),
        ),
        summary=Summary(
            beginning_balance=beginning,
            ending_balance=ending,
            deposits_total=0.0,
            withdrawals_total=0.0,
        ),
        transactions=[],
    )


async def test_clean_chain_passes():
    s1 = _stmt("2025-01-01", "2025-01-31", 1000.0, 1500.0)
    s2 = _stmt("2025-02-01", "2025-02-28", 1500.0, 1700.0)
    s3 = _stmt("2025-03-01", "2025-03-31", 1700.0, 2000.0)
    issues = await audit_continuity([s1, s2, s3])
    assert issues == []


async def test_break_detected():
    s1 = _stmt("2025-01-01", "2025-01-31", 1000.0, 1500.0)
    s2 = _stmt("2025-02-01", "2025-02-28", 1450.0, 1700.0)
    issues = await audit_continuity([s1, s2])
    assert len(issues) == 1
    assert abs(issues[0].delta + 50.0) < 0.01
    assert issues[0].account_last4 == "4664"


async def test_different_accounts_dont_interfere():
    a = _stmt("2025-01-01", "2025-01-31", 1000.0, 1500.0, last4="0001")
    b = _stmt("2025-01-01", "2025-01-31", 50.0, 250.0, last4="0002")
    issues = await audit_continuity([a, b])
    assert issues == []


async def test_gap_in_chain_is_skipped():
    s1 = _stmt("2025-01-01", "2025-01-31", 1000.0, 1500.0)
    s2 = _stmt("2025-07-01", "2025-07-31", 99.0, 250.0)
    issues = await audit_continuity([s1, s2])
    assert issues == []
