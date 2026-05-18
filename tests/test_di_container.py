import pytest
from dishka import make_async_container

from dobs.application.commands.cache.bust_cache import BustCacheHandler
from dobs.application.commands.cache.clear_cache import ClearCacheHandler
from dobs.application.commands.extraction.enrich_transactions import EnrichTransactionsHandler
from dobs.application.commands.extraction.extract_statement import ExtractStatementHandler
from dobs.application.commands.extraction.extract_summary import ExtractSummaryHandler
from dobs.application.commands.extraction.extract_transactions import ExtractTransactionsHandler
from dobs.application.commands.extraction.extract_transactions_hybrid import (
    ExtractTransactionsHybridHandler,
)
from dobs.application.commands.extraction.prevalidate_document import PrevalidateDocumentHandler
from dobs.application.commands.extraction.repair_statement import RepairStatementHandler
from dobs.application.commands.review.record_review import RecordReviewHandler
from dobs.application.ports.audit_sink import AuditSinkPort
from dobs.application.ports.cache import StatementCachePort
from dobs.application.ports.event_bus import EventBusPort
from dobs.application.ports.job_queue import JobStorePort
from dobs.application.ports.lessons_store import LessonsStorePort
from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.application.ports.ocr_engine import OcrEnginePort
from dobs.application.ports.review_store import ReviewStorePort
from dobs.application.ports.telemetry_collector import TelemetryCollectorPort
from dobs.application.ports.vendor_enricher import VendorEnricherPort
from dobs.application.ports.vendor_lookup import VendorLookupPort
from dobs.application.queries.diff_extractions import DiffExtractionsHandler
from dobs.application.queries.estimate_cost import EstimateCostHandler
from dobs.application.queries.explain_anomaly import ExplainAnomalyHandler
from dobs.application.queries.get_audit_log import GetAuditLogHandler
from dobs.application.queries.get_cache_keys import GetCacheKeysHandler
from dobs.application.queries.get_reviews import GetReviewsHandler
from dobs.application.queries.get_telemetry import GetTelemetryHandler
from dobs.application.queries.get_tiers import GetTiersHandler
from dobs.infrastructure.adapters.jobs.background_runner import BackgroundJobRunner
from dobs.infrastructure.adapters.replay.replaying_extract_handler import ReplayingExtractHandler
from dobs.main.di import build_providers

_PORTS = [
    AuditSinkPort,
    StatementCachePort,
    EventBusPort,
    JobStorePort,
    LessonsStorePort,
    LLMBackendPort,
    OcrEnginePort,
    ReviewStorePort,
    TelemetryCollectorPort,
    VendorEnricherPort,
    VendorLookupPort,
]

_HANDLERS = [
    BustCacheHandler,
    ClearCacheHandler,
    EnrichTransactionsHandler,
    ExtractStatementHandler,
    ExtractSummaryHandler,
    ExtractTransactionsHandler,
    ExtractTransactionsHybridHandler,
    PrevalidateDocumentHandler,
    RepairStatementHandler,
    RecordReviewHandler,
    DiffExtractionsHandler,
    EstimateCostHandler,
    ExplainAnomalyHandler,
    GetAuditLogHandler,
    GetCacheKeysHandler,
    GetReviewsHandler,
    GetTelemetryHandler,
    GetTiersHandler,
    BackgroundJobRunner,
    ReplayingExtractHandler,
]


@pytest.mark.parametrize("dep", _PORTS + _HANDLERS, ids=[d.__name__ for d in _PORTS + _HANDLERS])
async def test_di_container_resolves(dep):
    container = make_async_container(*build_providers())
    try:
        async with container() as scope:
            instance = await scope.get(dep)
            assert instance is not None
    finally:
        await container.close()
