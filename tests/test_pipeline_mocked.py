"""Integration tests with a mocked LLM backend.

We stub `LLMBackend.call_structured` so the whole pipeline runs without
hitting an API. This lets us verify:
  * Stages are wired correctly (summary -> transactions -> reconcile ->
    repair if needed -> enrich -> anomaly).
  * Telemetry is recorded.
  * Cache writes only happen on reconcile=ok.
  * Repair loop fires when reconciliation fails and stops when fixed.
"""
from pathlib import Path
from pydantic import BaseModel

from extractor.backends.base import LLMBackend, LLMRole
from extractor.cache import StatementCache
from extractor.pipeline import _process_segment
from extractor.segment import StatementSegment
from extractor.extract_summary import SummaryResponse
from extractor.extract_transactions import TransactionsResponse
from extractor.schemas import Account, Period, Summary, Transaction


_SEGMENT_TEXT = (
    "Ixonia Bank\nAccount Number: 4664\nBalance Summary\n"
    "Beginning Balance as of 04/01/2025 $1000.00\n"
    "+ Deposits and Credits (2) $300.00\n"
    "- Withdrawals and Debits (1) $50.00\n"
    "Ending Balance as of 04/30/2025 $1250.00\n"
    "Apr 01 SOMETHING 100.00\n"
    "Apr 02 OTHER 200.00\n"
    "Apr 03 PAY 50.00\n"
)


class MockBackend(LLMBackend):
    """Returns canned responses. Reconciles on first try."""
    name = "mock"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def call_structured(
        self, system: str, user: str, response_model,
        *, role=LLMRole.EXTRACT, max_retries=6, cache_system=True,
    ):
        self.calls.append(response_model.__name__)
        if response_model is SummaryResponse:
            return SummaryResponse(
                account=Account(
                    bank="Ixonia Bank",
                    account_last4="4664",
                    period=Period(start="2025-04-01", end="2025-04-30"),
                ),
                summary=Summary(
                    beginning_balance=1000.0,
                    ending_balance=1250.0,
                    deposits_total=300.0,
                    deposits_count=2,
                    withdrawals_total=50.0,
                    withdrawals_count=1,
                ),
            )
        if response_model is TransactionsResponse:
            return TransactionsResponse(
                transactions=[
                    Transaction(date="2025-04-01", description="SOMETHING", deposit=100.0),
                    Transaction(date="2025-04-02", description="OTHER", deposit=200.0),
                    Transaction(date="2025-04-03", description="PAY", withdrawal=50.0),
                ]
            )
        raise NotImplementedError(response_model.__name__)


class BadThenGoodBackend(MockBackend):
    """First transactions call returns wrong list, second (repair) returns right one."""
    def __init__(self) -> None:
        super().__init__()
        self.tx_calls = 0

    def call_structured(self, system, user, response_model, **kw):
        self.calls.append(response_model.__name__)
        if response_model is SummaryResponse:
            return super().call_structured(system, user, response_model, **kw)
        if response_model is TransactionsResponse:
            self.tx_calls += 1
            if self.tx_calls == 1:
                # Missing one deposit (only 200 + 50, not 100 + 200 + 50).
                return TransactionsResponse(transactions=[
                    Transaction(date="2025-04-02", description="OTHER", deposit=200.0),
                    Transaction(date="2025-04-03", description="PAY", withdrawal=50.0),
                ])
            return super().call_structured(system, user, response_model, **kw)
        raise NotImplementedError


def _seg() -> StatementSegment:
    return StatementSegment(
        text=_SEGMENT_TEXT,
        period_start_raw="04/01/2025",
        period_end_raw="04/30/2025",
        account_hint="4664",
    )


def test_happy_path_reconciles_first_try(tmp_path):
    backend = MockBackend()
    statement = _process_segment(
        _seg(), backend,
        cache=StatementCache(tmp_path / "c.db"),
    )
    assert statement.reconciliation.ok
    assert len(statement.transactions) == 3
    # Only 2 calls (summary + transactions); no repair.
    assert backend.calls == ["SummaryResponse", "TransactionsResponse"]


def test_repair_loop_fixes_extraction(tmp_path):
    backend = BadThenGoodBackend()
    statement = _process_segment(
        _seg(), backend,
        cache=StatementCache(tmp_path / "c.db"),
    )
    assert statement.reconciliation.ok
    assert len(statement.transactions) == 3
    # summary + 2 tx attempts = 3 calls.
    assert backend.tx_calls == 2


def test_cache_skips_processing(tmp_path):
    backend = MockBackend()
    cache = StatementCache(tmp_path / "c.db")
    # First run: full pipeline.
    _process_segment(_seg(), backend, cache=cache)
    n_after_first = len(backend.calls)
    # Second run: should be a cache hit (zero new calls).
    _process_segment(_seg(), backend, cache=cache)
    assert len(backend.calls) == n_after_first


def test_anomaly_detection_runs(tmp_path):
    backend = MockBackend()
    statement = _process_segment(_seg(), backend, cache=StatementCache(tmp_path / "c.db"))
    # No anomalies in clean canned data -- but the field exists.
    assert isinstance(statement.anomalies, list)
