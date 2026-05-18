from __future__ import annotations

import os
from pathlib import Path

from dishka import Provider, Scope, provide

from dobs.application.commands.cache.bust_cache import BustCacheHandler
from dobs.application.commands.cache.clear_cache import ClearCacheHandler
from dobs.application.commands.extraction.enrich_transactions import EnrichTransactionsHandler
from dobs.application.commands.extraction.extract_statement import ExtractStatementHandler
from dobs.application.commands.extraction.extract_summary import ExtractSummaryHandler
from dobs.application.commands.extraction.extract_transactions import ExtractTransactionsHandler
from dobs.application.commands.extraction.extract_transactions_hybrid import ExtractTransactionsHybridHandler
from dobs.application.commands.extraction.prevalidate_document import PrevalidateDocumentHandler
from dobs.application.commands.extraction.repair_statement import RepairStatementHandler
from dobs.application.commands.review.record_review import RecordReviewHandler
from dobs.application.ports.audit_sink import AuditSinkPort
from dobs.application.ports.cache import StatementCachePort
from dobs.application.ports.event_bus import EventBusPort
from dobs.application.ports.lessons_store import LessonsStorePort
from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.application.ports.ocr_engine import OcrEnginePort
from dobs.application.ports.review_store import ReviewStorePort
from dobs.application.ports.telemetry_collector import TelemetryCollectorPort
from dobs.application.ports.vendor_lookup import VendorLookupPort
from dobs.application.queries.diff_extractions import DiffExtractionsHandler
from dobs.application.queries.estimate_cost import EstimateCostHandler
from dobs.application.queries.explain_anomaly import ExplainAnomalyHandler
from dobs.application.queries.get_audit_log import GetAuditLogHandler
from dobs.application.queries.get_cache_keys import GetCacheKeysHandler
from dobs.application.queries.get_reviews import GetReviewsHandler
from dobs.application.queries.get_telemetry import GetTelemetryHandler
from dobs.application.queries.get_tiers import GetTiersHandler
from dobs.application.services.chunking import TransactionChunker
from dobs.application.services.cost_estimate import CostEstimator
from dobs.application.services.lessons_helpers import LessonsHelper
from dobs.application.services.segmenter import StatementSegmenter
from dobs.domain.services.anomaly_detector import AnomalyDetector
from dobs.domain.services.continuity_auditor import ContinuityAuditor
from dobs.domain.services.forensic_detector import ForensicAnomalyDetector
from dobs.domain.services.prompt_sanitizer import PromptSanitizer
from dobs.domain.services.reconcile import Reconciler
from dobs.domain.services.recurring_detector import RecurringDetector
from dobs.domain.services.row_parser import RowParser
from dobs.infrastructure.adapters.audit.sqlite_audit_sink import AUDIT_SCHEMA, SqliteAuditSink
from dobs.infrastructure.adapters.cache.resolver import open_cache
from dobs.infrastructure.adapters.event_bus.asyncio_event_bus import AsyncioEventBus
from dobs.infrastructure.adapters.lessons.sqlite_lessons_store import LESSONS_SCHEMA, SqliteLessonsStore
from dobs.infrastructure.adapters.llm.anthropic_backend import AnthropicLLMBackend
from dobs.infrastructure.adapters.ocr.composite_engine import CompositeOcrEngine
from dobs.infrastructure.adapters.ocr.file_reader import FileReader
from dobs.infrastructure.adapters.ocr.tesseract_engine import (
    OCR_CACHE_SCHEMA, OcrCacheStore, TesseractOcrEngine,
)
from dobs.infrastructure.adapters.ocr.vision_engine import VisionOcrEngine
from dobs.infrastructure.adapters.replay.demo_replay import DemoReplayPlayer, is_replay_enabled
from dobs.infrastructure.adapters.review.sqlite_review_store import REVIEW_SCHEMA, SqliteReviewStore
from dobs.infrastructure.adapters.telemetry.call_stats_collector import CallStatsCollector
from dobs.infrastructure.adapters.vendor.clearbit_lookup import (
    VENDOR_CACHE_SCHEMA, ClearbitVendorLookup, VendorCacheStore,
)
from dobs.infrastructure.adapters.vendor.composite_lookup import CompositeVendorLookup
from dobs.infrastructure.adapters.vendor.seed_lookup import SeedVendorLookup
from dobs.infrastructure.persistence.sqlite_session import SqliteSessionFactory
from dobs.main.config.settings import AppSettings, get_settings

from typing import NewType


AuditSessions = NewType("AuditSessions", SqliteSessionFactory)
ReviewSessions = NewType("ReviewSessions", SqliteSessionFactory)
LessonsSessions = NewType("LessonsSessions", SqliteSessionFactory)
OcrCacheSessions = NewType("OcrCacheSessions", SqliteSessionFactory)
VendorCacheSessions = NewType("VendorCacheSessions", SqliteSessionFactory)


class _EventBusEmitAdapter:
    def __init__(self, /, *, bus: AsyncioEventBus) -> None:
        self._bus = bus

    async def emit(self, event_name: str, data: dict) -> None:
        await self._bus.publish(event_name, data)

    async def publish(self, event_name: str, data: dict) -> None:
        await self._bus.publish(event_name, data)


class _VendorLookupWithEnrich:
    def __init__(self, /, *, inner: CompositeVendorLookup) -> None:
        self._inner = inner

    async def lookup(self, raw: str):
        return await self._inner.lookup(raw)

    async def enrich_in_place(self, records: list[dict]) -> None:
        for rec in records:
            raw = rec.get("description") or ""
            try:
                info = await self._inner.lookup(raw)
                if info.canonical_name:
                    rec["vendor"] = info.canonical_name
                if info.logo_url:
                    rec["vendor_logo"] = info.logo_url
            except Exception:
                pass


class _ReviewStoreAdapter:
    def __init__(self, /, *, store: SqliteReviewStore) -> None:
        self._store = store

    async def record_decision(
        self,
        *,
        statement_key: str,
        tx_index: int,
        decision: str,
        reviewer: str | None = None,
        note: str | None = None,
    ) -> int:
        return await self._store.record(
            statement_key=statement_key, tx_index=tx_index,
            decision=decision, reviewer=reviewer, note=note,
        )

    async def get_decisions(self, statement_key: str) -> list[dict]:
        return list((await self._store.latest_for_statement(statement_key)).values())

    async def record(self, **kwargs) -> int:
        return await self._store.record(**kwargs)

    async def latest_for_statement(self, statement_key: str) -> dict:
        return await self._store.latest_for_statement(statement_key)

    async def history(self, statement_key: str, tx_index: int) -> list[dict]:
        return await self._store.history(statement_key, tx_index)


class _ReplayingExtractHandler:
    def __init__(self, /, *, inner: ExtractStatementHandler, replay_player: DemoReplayPlayer, event_bus) -> None:
        self._inner = inner
        self._replay = replay_player
        self._event_bus = event_bus

    async def __call__(self, command):
        if is_replay_enabled():
            bus = self._event_bus

            def log_event(name: str, data: dict) -> None:
                import asyncio as _asyncio
                try:
                    loop = _asyncio.get_running_loop()
                    loop.create_task(bus.publish(name, data))
                except RuntimeError:
                    pass

            return await self._replay.replay(
                log_event=log_event,
                tier=getattr(command, "tier", None),
            )
        return await self._inner(command)


class SettingsProvider(Provider):
    scope = Scope.APP

    @provide
    def settings(self) -> AppSettings:
        return get_settings()


class InfrastructureProvider(Provider):
    scope = Scope.APP

    @provide
    def telemetry(self) -> TelemetryCollectorPort:
        return CallStatsCollector()

    @provide
    def llm(self, settings: AppSettings, telemetry: TelemetryCollectorPort) -> LLMBackendPort:
        backend_name = settings.backend or os.getenv("EXTRACTOR_BACKEND", "anthropic")
        if backend_name == "ollama":
            from dobs.infrastructure.adapters.llm.ollama_backend import OllamaLLMBackend
            return OllamaLLMBackend(telemetry=telemetry)
        return AnthropicLLMBackend(telemetry=telemetry)

    @provide
    async def cache(self, settings: AppSettings) -> StatementCachePort:
        url = settings.cache_url or os.getenv("EXTRACTOR_CACHE_URL", "out/cache.db")
        return await open_cache(url)

    @provide
    def audit_sessions(self, settings: AppSettings) -> AuditSessions:
        return AuditSessions(SqliteSessionFactory(
            db_path=Path(settings.audit_log_db), schema=AUDIT_SCHEMA,
        ))

    @provide
    def review_sessions(self, settings: AppSettings) -> ReviewSessions:
        return ReviewSessions(SqliteSessionFactory(
            db_path=Path(settings.review_db), schema=REVIEW_SCHEMA,
        ))

    @provide
    def lessons_sessions(self) -> LessonsSessions:
        return LessonsSessions(SqliteSessionFactory(
            db_path=Path("out/lessons.db"), schema=LESSONS_SCHEMA,
        ))

    @provide
    def ocr_cache_sessions(self, settings: AppSettings) -> OcrCacheSessions:
        return OcrCacheSessions(SqliteSessionFactory(
            db_path=Path(settings.ocr_cache_db), schema=OCR_CACHE_SCHEMA,
        ))

    @provide
    def vendor_cache_sessions(self, settings: AppSettings) -> VendorCacheSessions:
        return VendorCacheSessions(SqliteSessionFactory(
            db_path=Path(settings.vendor_cache_db), schema=VENDOR_CACHE_SCHEMA,
        ))

    @provide
    def ocr_cache(self, sessions: OcrCacheSessions) -> OcrCacheStore:
        return OcrCacheStore(sessions=sessions)

    @provide
    def vendor_cache(self, sessions: VendorCacheSessions) -> VendorCacheStore:
        return VendorCacheStore(sessions=sessions)

    @provide
    def audit(self, sessions: AuditSessions) -> AuditSinkPort:
        return SqliteAuditSink(sessions=sessions)

    @provide
    def review_store_raw(self, sessions: ReviewSessions) -> SqliteReviewStore:
        return SqliteReviewStore(sessions=sessions)

    @provide
    def review(self, store: SqliteReviewStore) -> ReviewStorePort:
        return _ReviewStoreAdapter(store=store)

    @provide
    def lessons(self, sessions: LessonsSessions) -> LessonsStorePort:
        return SqliteLessonsStore(sessions=sessions)

    @provide
    def vendor_composite(self, vendor_cache: VendorCacheStore) -> CompositeVendorLookup:
        seed = SeedVendorLookup()
        clearbit = ClearbitVendorLookup(cache=vendor_cache)
        return CompositeVendorLookup(seed=seed, clearbit=clearbit)

    @provide
    def vendor(self, composite: CompositeVendorLookup) -> VendorLookupPort:
        return _VendorLookupWithEnrich(inner=composite)

    @provide
    def event_bus(self) -> EventBusPort:
        return _EventBusEmitAdapter(bus=AsyncioEventBus())

    @provide
    def ocr(self, llm: LLMBackendPort, ocr_cache: OcrCacheStore) -> OcrEnginePort:
        file_reader = FileReader()
        tesseract = TesseractOcrEngine(file_reader=file_reader, cache=ocr_cache)
        vision: VisionOcrEngine | None = None
        if getattr(llm, "supports_vision", lambda: False)():
            vision = VisionOcrEngine(backend=llm)
        opendataloader: OcrEnginePort | None = None
        jar = os.getenv("OPENDATALOADER_JAR")
        if jar and Path(jar).exists():
            from dobs.infrastructure.adapters.ocr.opendataloader_engine import OpenDataLoaderOcrEngine
            try:
                opendataloader = OpenDataLoaderOcrEngine(jar_path=Path(jar))
            except Exception:
                opendataloader = None
        return CompositeOcrEngine(
            file_reader=file_reader, tesseract=tesseract, vision=vision,
            opendataloader=opendataloader,
        )

    @provide
    def replay_player(self) -> DemoReplayPlayer:
        return DemoReplayPlayer()


class DomainServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def reconciler(self) -> Reconciler:
        return Reconciler()

    @provide
    def anomaly_detector(self) -> AnomalyDetector:
        return AnomalyDetector()

    @provide
    def continuity_auditor(self) -> ContinuityAuditor:
        return ContinuityAuditor()

    @provide
    def forensic_detector(self) -> ForensicAnomalyDetector:
        return ForensicAnomalyDetector()

    @provide
    def recurring_detector(self) -> RecurringDetector:
        return RecurringDetector()

    @provide
    def prompt_sanitizer(self) -> PromptSanitizer:
        return PromptSanitizer()

    @provide
    def row_parser(self) -> RowParser:
        return RowParser()


class ApplicationServicesProvider(Provider):
    scope = Scope.APP

    @provide
    def segmenter(self, sanitizer: PromptSanitizer) -> StatementSegmenter:
        return StatementSegmenter(sanitizer=sanitizer)

    @provide
    def chunker(self) -> TransactionChunker:
        return TransactionChunker()

    @provide
    def lessons_helper(self) -> LessonsHelper:
        return LessonsHelper()

    @provide
    def cost_estimator(self) -> CostEstimator:
        return CostEstimator()


class ExtractionHandlersProvider(Provider):
    scope = Scope.APP

    @provide
    def hybrid(
        self,
        llm: LLMBackendPort,
        sanitizer: PromptSanitizer,
        row_parser: RowParser,
    ) -> ExtractTransactionsHybridHandler:
        return ExtractTransactionsHybridHandler(
            llm=llm, sanitizer=sanitizer, row_parser=row_parser,
        )

    @provide
    def summary(
        self,
        llm: LLMBackendPort,
        sanitizer: PromptSanitizer,
    ) -> ExtractSummaryHandler:
        return ExtractSummaryHandler(llm=llm, sanitizer=sanitizer)

    @provide
    def transactions(
        self,
        llm: LLMBackendPort,
        hybrid: ExtractTransactionsHybridHandler,
        sanitizer: PromptSanitizer,
        chunker: TransactionChunker,
        lessons_helper: LessonsHelper,
        lessons: LessonsStorePort,
    ) -> ExtractTransactionsHandler:
        return ExtractTransactionsHandler(
            llm=llm, hybrid=hybrid, sanitizer=sanitizer,
            chunker=chunker, lessons_helper=lessons_helper, lessons=lessons,
        )

    @provide
    def repair(
        self,
        llm: LLMBackendPort,
        sanitizer: PromptSanitizer,
        reconciler: Reconciler,
    ) -> RepairStatementHandler:
        return RepairStatementHandler(
            llm=llm, sanitizer=sanitizer, reconciler=reconciler,
        )

    @provide
    def enrich(self, llm: LLMBackendPort) -> EnrichTransactionsHandler:
        return EnrichTransactionsHandler(llm=llm)

    @provide
    def prevalidate(self, llm: LLMBackendPort) -> PrevalidateDocumentHandler:
        return PrevalidateDocumentHandler(llm=llm)

    @provide
    def extract_real(
        self,
        ocr: OcrEnginePort,
        cache: StatementCachePort,
        audit: AuditSinkPort,
        lessons: LessonsStorePort,
        event_bus: EventBusPort,
        telemetry: TelemetryCollectorPort,
        summary: ExtractSummaryHandler,
        transactions: ExtractTransactionsHandler,
        repair: RepairStatementHandler,
        enrich_cmd: EnrichTransactionsHandler,
        vendor: VendorLookupPort,
        llm: LLMBackendPort,
        segmenter: StatementSegmenter,
        reconciler: Reconciler,
        anomaly_detector: AnomalyDetector,
        continuity_auditor: ContinuityAuditor,
        forensic_detector: ForensicAnomalyDetector,
        recurring_detector: RecurringDetector,
        lessons_helper: LessonsHelper,
    ) -> ExtractStatementHandler:
        return ExtractStatementHandler(
            ocr=ocr, cache=cache, audit=audit, lessons=lessons,
            event_bus=event_bus, telemetry=telemetry,
            summary=summary, transactions=transactions, repair=repair,
            enrich_cmd=enrich_cmd, vendor=vendor, llm=llm,
            segmenter=segmenter, reconciler=reconciler,
            anomaly_detector=anomaly_detector, continuity_auditor=continuity_auditor,
            forensic_detector=forensic_detector, recurring_detector=recurring_detector,
            lessons_helper=lessons_helper,
        )

    @provide
    def extract(
        self,
        inner: ExtractStatementHandler,
        replay_player: DemoReplayPlayer,
        event_bus: EventBusPort,
    ) -> _ReplayingExtractHandler:
        return _ReplayingExtractHandler(
            inner=inner, replay_player=replay_player, event_bus=event_bus,
        )


class QueryHandlersProvider(Provider):
    scope = Scope.APP

    @provide
    def bust_cache(self, cache: StatementCachePort) -> BustCacheHandler:
        return BustCacheHandler(cache=cache)

    @provide
    def clear_cache(self, cache: StatementCachePort) -> ClearCacheHandler:
        return ClearCacheHandler(cache=cache)

    @provide
    def record_review(self, review_store: ReviewStorePort) -> RecordReviewHandler:
        return RecordReviewHandler(review_store=review_store)

    @provide
    def get_audit_log(self, audit: AuditSinkPort) -> GetAuditLogHandler:
        return GetAuditLogHandler(audit=audit)

    @provide
    def get_cache_keys(self, cache: StatementCachePort) -> GetCacheKeysHandler:
        return GetCacheKeysHandler(cache=cache)

    @provide
    def get_telemetry(self, telemetry: TelemetryCollectorPort) -> GetTelemetryHandler:
        return GetTelemetryHandler(telemetry=telemetry)

    @provide
    def get_tiers(self) -> GetTiersHandler:
        return GetTiersHandler()

    @provide
    def get_reviews(self, review_store: ReviewStorePort) -> GetReviewsHandler:
        return GetReviewsHandler(review_store=review_store)

    @provide
    def explain_anomaly(self, llm: LLMBackendPort) -> ExplainAnomalyHandler:
        return ExplainAnomalyHandler(llm=llm)

    @provide
    def diff(self) -> DiffExtractionsHandler:
        return DiffExtractionsHandler()

    @provide
    def estimate_cost(self, estimator: CostEstimator) -> EstimateCostHandler:
        return EstimateCostHandler(estimator=estimator)


def build_providers() -> list[Provider]:
    return [
        SettingsProvider(),
        InfrastructureProvider(),
        DomainServicesProvider(),
        ApplicationServicesProvider(),
        ExtractionHandlersProvider(),
        QueryHandlersProvider(),
    ]
