from __future__ import annotations

import os
from pathlib import Path

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
from dobs.application.queries.diff_extractions import DiffExtractionsHandler
from dobs.application.queries.estimate_cost import EstimateCostHandler
from dobs.application.queries.explain_anomaly import ExplainAnomalyHandler
from dobs.application.queries.get_audit_log import GetAuditLogHandler
from dobs.application.queries.get_cache_keys import GetCacheKeysHandler
from dobs.application.queries.get_reviews import GetReviewsHandler
from dobs.application.queries.get_telemetry import GetTelemetryHandler
from dobs.application.queries.get_tiers import GetTiersHandler
from dobs.infrastructure.adapters.audit.sqlite_audit_sink import SqliteAuditSink
from dobs.infrastructure.adapters.cache.resolver import open_cache
from dobs.infrastructure.adapters.event_bus.asyncio_event_bus import AsyncioEventBus
from dobs.infrastructure.adapters.lessons.sqlite_lessons_store import SqliteLessonsStore
from dobs.infrastructure.adapters.llm.anthropic_backend import AnthropicLLMBackend
from dobs.infrastructure.adapters.ocr.composite_engine import CompositeOcrEngine
from dobs.infrastructure.adapters.ocr.file_reader import FileReader
from dobs.infrastructure.adapters.ocr.tesseract_engine import TesseractOcrEngine
from dobs.infrastructure.adapters.ocr.vision_engine import VisionOcrEngine
from dobs.infrastructure.adapters.review.sqlite_review_store import SqliteReviewStore
from dobs.infrastructure.adapters.telemetry.call_stats_collector import CallStatsCollector
from dobs.infrastructure.adapters.vendor.clearbit_lookup import ClearbitVendorLookup
from dobs.infrastructure.adapters.vendor.composite_lookup import CompositeVendorLookup
from dobs.infrastructure.adapters.vendor.seed_lookup import SeedVendorLookup
from dobs.main.config.settings import AppSettings


class _EventBusEmitAdapter:
    """Wraps AsyncioEventBus to expose .emit() used by ExtractStatementHandler."""

    def __init__(self, /, *, bus: AsyncioEventBus) -> None:
        self._bus = bus

    async def emit(self, event_name: str, data: dict) -> None:
        await self._bus.publish(event_name, data)

    async def publish(self, event_name: str, data: dict) -> None:
        await self._bus.publish(event_name, data)


class _VendorLookupWithEnrich:
    """Wraps CompositeVendorLookup to add enrich_in_place() expected by ExtractStatementHandler."""

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
    """Wraps SqliteReviewStore to expose record_decision() and get_decisions() used by handlers."""

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
            statement_key=statement_key,
            tx_index=tx_index,
            decision=decision,
            reviewer=reviewer,
            note=note,
        )

    async def get_decisions(self, statement_key: str) -> list[dict]:
        result = await self._store.latest_for_statement(statement_key)
        return list(result.values())

    async def record(
        self,
        *,
        statement_key: str,
        tx_index: int,
        decision,
        reviewer: str | None = None,
        note: str | None = None,
    ) -> int:
        return await self._store.record(
            statement_key=statement_key,
            tx_index=tx_index,
            decision=decision,
            reviewer=reviewer,
            note=note,
        )

    async def latest_for_statement(self, statement_key: str) -> dict:
        return await self._store.latest_for_statement(statement_key)

    async def history(self, statement_key: str, tx_index: int) -> list[dict]:
        return await self._store.history(statement_key, tx_index)


class _CachePlaceholder:
    """Defers async cache initialisation by forwarding to the container on each call."""

    def __init__(self, /, *, container: "Container") -> None:
        self._container = container

    async def _c(self):
        return await self._container.cache()

    async def get(self, key: str):
        return await (await self._c()).get(key)

    async def put(self, key: str, statement) -> None:
        await (await self._c()).put(key, statement)

    async def delete(self, key: str) -> bool:
        return await (await self._c()).delete(key)

    async def clear(self) -> int:
        return await (await self._c()).clear()

    async def keys(self, limit: int = 200) -> list[dict]:
        return await (await self._c()).keys(limit=limit)

    async def stats(self) -> dict:
        return await (await self._c()).stats()


class Container:
    def __init__(self, /, *, settings: AppSettings) -> None:
        self._settings = settings
        self._telemetry: CallStatsCollector | None = None
        self._llm = None
        self._cache = None
        self._audit: SqliteAuditSink | None = None
        self._review: _ReviewStoreAdapter | None = None
        self._lessons: SqliteLessonsStore | None = None
        self._ocr: CompositeOcrEngine | None = None
        self._vendor: _VendorLookupWithEnrich | None = None
        self._event_bus: _EventBusEmitAdapter | None = None
        self._cache_placeholder: _CachePlaceholder | None = None

    def telemetry(self) -> CallStatsCollector:
        if self._telemetry is None:
            self._telemetry = CallStatsCollector()
        return self._telemetry

    def llm(self):
        if self._llm is None:
            tel = self.telemetry()
            backend_name = self._settings.backend or os.getenv("EXTRACTOR_BACKEND", "anthropic")
            if backend_name == "ollama":
                from dobs.infrastructure.adapters.llm.ollama_backend import OllamaLLMBackend
                self._llm = OllamaLLMBackend(telemetry=tel)
            else:
                self._llm = AnthropicLLMBackend(telemetry=tel)
        return self._llm

    async def cache(self):
        if self._cache is None:
            url = self._settings.cache_url or os.getenv("EXTRACTOR_CACHE_URL", "out/cache.db")
            self._cache = await open_cache(url)
        return self._cache

    def _cache_proxy(self) -> _CachePlaceholder:
        if self._cache_placeholder is None:
            self._cache_placeholder = _CachePlaceholder(container=self)
        return self._cache_placeholder

    def audit(self) -> SqliteAuditSink:
        if self._audit is None:
            self._audit = SqliteAuditSink(db_path=Path(self._settings.audit_log_db))
        return self._audit

    def review(self) -> _ReviewStoreAdapter:
        if self._review is None:
            store = SqliteReviewStore(db_path=Path(self._settings.review_db))
            self._review = _ReviewStoreAdapter(store=store)
        return self._review

    def lessons(self) -> SqliteLessonsStore:
        if self._lessons is None:
            self._lessons = SqliteLessonsStore(db_path=Path("out/lessons.db"))
        return self._lessons

    def vendor(self) -> _VendorLookupWithEnrich:
        if self._vendor is None:
            seed = SeedVendorLookup()
            clearbit = ClearbitVendorLookup()
            composite = CompositeVendorLookup(seed=seed, clearbit=clearbit)
            self._vendor = _VendorLookupWithEnrich(inner=composite)
        return self._vendor

    def event_bus(self) -> _EventBusEmitAdapter:
        if self._event_bus is None:
            bus = AsyncioEventBus()
            self._event_bus = _EventBusEmitAdapter(bus=bus)
        return self._event_bus

    def ocr(self) -> CompositeOcrEngine:
        if self._ocr is None:
            file_reader = FileReader()
            tesseract = TesseractOcrEngine(file_reader=file_reader)
            vision: VisionOcrEngine | None = None
            llm = self.llm()
            if getattr(llm, "supports_vision", lambda: False)():
                vision = VisionOcrEngine(backend=llm)
            self._ocr = CompositeOcrEngine(
                file_reader=file_reader,
                tesseract=tesseract,
                vision=vision,
            )
        return self._ocr

    def hybrid_handler(self) -> ExtractTransactionsHybridHandler:
        return ExtractTransactionsHybridHandler(llm=self.llm())

    def summary_handler(self) -> ExtractSummaryHandler:
        return ExtractSummaryHandler(llm=self.llm())

    def transactions_handler(self) -> ExtractTransactionsHandler:
        return ExtractTransactionsHandler(
            llm=self.llm(),
            hybrid=self.hybrid_handler(),
            lessons=self.lessons(),
        )

    def repair_handler(self) -> RepairStatementHandler:
        return RepairStatementHandler(llm=self.llm())

    def enrich_handler(self) -> EnrichTransactionsHandler:
        return EnrichTransactionsHandler(llm=self.llm())

    def extract_handler(self) -> ExtractStatementHandler:
        return ExtractStatementHandler(
            ocr=self.ocr(),
            cache=self._cache_proxy(),
            audit=self.audit(),
            lessons=self.lessons(),
            event_bus=self.event_bus(),
            telemetry=self.telemetry(),
            summary=self.summary_handler(),
            transactions=self.transactions_handler(),
            repair=self.repair_handler(),
            enrich_cmd=self.enrich_handler(),
            vendor=self.vendor(),
            llm=self.llm(),
        )

    def prevalidate_handler(self) -> PrevalidateDocumentHandler:
        return PrevalidateDocumentHandler(llm=self.llm())

    def bust_cache_handler(self) -> BustCacheHandler:
        return BustCacheHandler(cache=self._cache_proxy())

    def clear_cache_handler(self) -> ClearCacheHandler:
        return ClearCacheHandler(cache=self._cache_proxy())

    def record_review_handler(self) -> RecordReviewHandler:
        return RecordReviewHandler(review_store=self.review())

    def get_audit_log_handler(self) -> GetAuditLogHandler:
        return GetAuditLogHandler(audit=self.audit())

    def get_cache_keys_handler(self) -> GetCacheKeysHandler:
        return GetCacheKeysHandler(cache=self._cache_proxy())

    def get_telemetry_handler(self) -> GetTelemetryHandler:
        return GetTelemetryHandler(telemetry=self.telemetry())

    def get_tiers_handler(self) -> GetTiersHandler:
        return GetTiersHandler()

    def get_reviews_handler(self) -> GetReviewsHandler:
        return GetReviewsHandler(review_store=self.review())

    def explain_anomaly_handler(self) -> ExplainAnomalyHandler:
        return ExplainAnomalyHandler(llm=self.llm())

    def diff_handler(self) -> DiffExtractionsHandler:
        return DiffExtractionsHandler()

    def estimate_cost_handler(self) -> EstimateCostHandler:
        return EstimateCostHandler()


def build_container(settings: AppSettings | None = None) -> Container:
    if settings is None:
        from dobs.main.config.settings import get_settings
        settings = get_settings()
    return Container(settings=settings)
