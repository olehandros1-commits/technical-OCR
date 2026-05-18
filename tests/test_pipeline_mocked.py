from pydantic import BaseModel, ConfigDict

from dobs.application.commands.extraction.enrich_transactions import (
    EnrichTransactionsHandler,
)
from dobs.application.commands.extraction.extract_statement import (
    ExtractStatementCommand,
    ExtractStatementHandler,
)
from dobs.application.commands.extraction.extract_summary import (
    ExtractSummaryHandler,
)
from dobs.application.commands.extraction.extract_transactions import (
    ExtractTransactionsHandler,
)
from dobs.application.commands.extraction.extract_transactions_hybrid import (
    ExtractTransactionsHybridHandler,
)
from dobs.application.commands.extraction.repair_statement import (
    RepairStatementHandler,
)
from dobs.application.services.segmenter import StatementSegment
from dobs.domain.value_objects.account import Account
from dobs.domain.value_objects.llm_role import LLMRole
from dobs.domain.value_objects.period import Period
from dobs.domain.value_objects.summary import Summary
from dobs.domain.value_objects.transaction import Transaction
from dobs.infrastructure.adapters.cache.memory_cache import MemoryStatementCache

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

_ACCOUNT = Account(
    bank="Ixonia Bank",
    account_last4="4664",
    period=Period(start="2025-04-01", end="2025-04-30"),
)
_SUMMARY = Summary(
    beginning_balance=1000.0,
    ending_balance=1250.0,
    deposits_total=300.0,
    deposits_count=2,
    withdrawals_total=50.0,
    withdrawals_count=1,
)
_TRANSACTIONS = [
    Transaction(date="2025-04-01", description="SOMETHING", deposit=100.0),
    Transaction(date="2025-04-02", description="OTHER", deposit=200.0),
    Transaction(date="2025-04-03", description="PAY", withdrawal=50.0),
]


class _SummaryResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    account: Account
    summary: Summary


class _MockLLM:
    name = "mock"

    def __init__(self, tx_list=None) -> None:
        self.calls: list[str] = []
        self._tx_list = tx_list or _TRANSACTIONS

    async def call_structured(self, *, system, user, response_model, role=LLMRole.EXTRACT, **kw):
        self.calls.append(response_model.__name__)
        from dobs.application.commands.extraction.extract_summary import _SummaryResponse as SR
        from dobs.application.commands.extraction.extract_transactions_hybrid import (
            _TransactionsResult as TR,
        )

        if response_model is SR:
            return SR(account=_ACCOUNT, summary=_SUMMARY)
        if response_model is TR:
            return TR(transactions=list(self._tx_list))
        raise NotImplementedError(response_model.__name__)

    async def call_vision(self, **kw):
        raise NotImplementedError

    def supports_vision(self):
        return False


class _BadThenGoodLLM(_MockLLM):
    def __init__(self) -> None:
        super().__init__()
        self.tx_calls = 0

    async def call_structured(self, *, system, user, response_model, **kw):
        from dobs.application.commands.extraction.extract_summary import _SummaryResponse as SR
        from dobs.application.commands.extraction.extract_transactions_hybrid import (
            _TransactionsResult as TR,
        )

        self.calls.append(response_model.__name__)
        if response_model is SR:
            return SR(account=_ACCOUNT, summary=_SUMMARY)
        if response_model is TR:
            self.tx_calls += 1
            if self.tx_calls == 1:
                return TR(
                    transactions=[
                        Transaction(date="2025-04-02", description="OTHER", deposit=200.0),
                        Transaction(date="2025-04-03", description="PAY", withdrawal=50.0),
                    ]
                )
            return TR(transactions=list(_TRANSACTIONS))
        raise NotImplementedError


class _NullEventBus:
    async def publish(self, name, data):
        pass


class _NullAudit:
    async def record(self, ts, rec):
        return 1

    async def recent(self, limit=50):
        return []


class _NullTelemetry:
    def record(self, stats):
        pass

    def summary(self):
        return {}


class _NullVendorLookup:
    async def lookup(self, raw):
        from dobs.application.ports.vendor_lookup import VendorInfo

        return VendorInfo(raw=raw)

    async def enrich_in_place(self, txns):
        return 0


def _build_handler(llm, cache=None):
    from dobs.application.services.chunking import TransactionChunker
    from dobs.application.services.lessons_helpers import LessonsHelper
    from dobs.application.services.segmenter import StatementSegmenter
    from dobs.domain.services.anomaly_detector import AnomalyDetector
    from dobs.domain.services.continuity_auditor import ContinuityAuditor
    from dobs.domain.services.forensic_detector import ForensicAnomalyDetector
    from dobs.domain.services.prompt_sanitizer import PromptSanitizer
    from dobs.domain.services.reconcile import Reconciler
    from dobs.domain.services.recurring_detector import RecurringDetector
    from dobs.domain.services.row_parser import RowParser

    if cache is None:
        cache = MemoryStatementCache()
    sanitizer = PromptSanitizer()
    reconciler = Reconciler()
    row_parser = RowParser()
    chunker = TransactionChunker()
    lessons_helper = LessonsHelper()
    hybrid = ExtractTransactionsHybridHandler(
        llm=llm,
        sanitizer=sanitizer,
        row_parser=row_parser,
    )
    summary_h = ExtractSummaryHandler(llm=llm, sanitizer=sanitizer)
    tx_h = ExtractTransactionsHandler(
        llm=llm,
        hybrid=hybrid,
        sanitizer=sanitizer,
        chunker=chunker,
        lessons_helper=lessons_helper,
        lessons=None,
    )
    repair_h = RepairStatementHandler(
        llm=llm,
        sanitizer=sanitizer,
        reconciler=reconciler,
    )
    enrich_h = EnrichTransactionsHandler(llm=llm)
    return ExtractStatementHandler(
        ocr=None,
        cache=cache,
        audit=_NullAudit(),
        lessons=None,
        event_bus=_NullEventBus(),
        telemetry=_NullTelemetry(),
        summary=summary_h,
        transactions=tx_h,
        repair=repair_h,
        enrich_cmd=enrich_h,
        vendor=_NullVendorLookup(),
        llm=llm,
        segmenter=StatementSegmenter(),
        reconciler=reconciler,
        anomaly_detector=AnomalyDetector(),
        continuity_auditor=ContinuityAuditor(),
        forensic_detector=ForensicAnomalyDetector(),
        recurring_detector=RecurringDetector(),
        lessons_helper=lessons_helper,
    )


def _seg() -> StatementSegment:
    return StatementSegment(
        text=_SEGMENT_TEXT,
        period_start_raw="04/01/2025",
        period_end_raw="04/30/2025",
        account_hint="4664",
    )


async def test_happy_path_reconciles_first_try():
    llm = _MockLLM()
    handler = _build_handler(llm)
    seg = _seg()
    command = ExtractStatementCommand(
        pdf_path="",
        tenant="_default",
    )
    statement = await handler._process_segment_inner(seg, command)
    assert statement is not None
    assert statement.reconciliation.ok
    assert len(statement.transactions) == 3


async def test_repair_loop_fixes_extraction():
    llm = _BadThenGoodLLM()
    handler = _build_handler(llm)
    seg = _seg()
    command = ExtractStatementCommand(pdf_path="", tenant="_default")
    statement = await handler._process_segment_inner(seg, command)
    assert statement is not None
    assert statement.reconciliation.ok
    assert len(statement.transactions) == 3
    assert llm.tx_calls == 2


async def test_cache_skips_processing():
    llm = _MockLLM()
    cache = MemoryStatementCache()
    handler = _build_handler(llm, cache=cache)
    seg = _seg()
    command = ExtractStatementCommand(pdf_path="", tenant="_default")
    await handler._process_segment_inner(seg, command)
    n_after_first = len(llm.calls)
    await handler._process_segment_inner(seg, command)
    assert len(llm.calls) == n_after_first


async def test_anomaly_detection_runs():
    llm = _MockLLM()
    handler = _build_handler(llm)
    seg = _seg()
    command = ExtractStatementCommand(pdf_path="", tenant="_default")
    statement = await handler._process_segment_inner(seg, command)
    assert statement is not None
    assert isinstance(statement.anomalies, list)
