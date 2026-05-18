# Target Layout — dobs Clean Architecture Refactor

Concrete file-tree mapping from the current flat `extractor/` package to
a layered `dobs/` package, following the eclipse reference architecture.

---

## 1. File Mapping Table

### Current → Target

| Current `src/extractor/` file | Target `src/dobs/` location | Notes |
|---|---|---|
| **Domain layer (pure logic, no I/O)** | | |
| `schemas.py` (Period, Account, Summary, Transaction, Anomaly, SkippedRow, ReconciliationResult) | `domain/value_objects/period.py`, `domain/value_objects/tx_category.py`, `domain/value_objects/anomaly_kind.py`, `domain/value_objects/severity.py` (enums only) | Pydantic models move to application/common or stay as schemas in presentation; pure enums become domain value objects |
| `schemas.py` (Statement) | `domain/entities/statement.py` | Becomes a dataclass entity, not Pydantic |
| `reconcile.py` | `domain/services/reconcile.py` | Pure math, no I/O — domain service |
| `anomaly.py` | `domain/services/anomaly_detector.py` | Pure code, no I/O |
| `forensic.py` | `domain/services/forensic_detector.py` | Pure code, no I/O |
| `continuity.py` | `domain/services/continuity_auditor.py` | Pure code, no I/O |
| `recurring.py` | `domain/services/recurring_detector.py` | Pure code, no I/O |
| `parse_rows.py` | `domain/services/row_parser.py` | Pure regex, no I/O |
| `security.py` | `domain/services/prompt_sanitizer.py` | Pure text transforms |
| `prompts.py` | `domain/prompts.py` | Static string constants, no I/O |
| — (new) | `domain/common/specification.py` | Base Specification[T] from eclipse |
| — (new) | `domain/entities/base.py` | Entity[OIDType] base |
| — (new) | `domain/entities/audit_record.py` | AuditRecord entity |
| — (new) | `domain/entities/extraction_job.py` | ExtractionJob entity (job state) |
| — (new) | `domain/errors.py` | DomainError hierarchy |
| **Application layer (use cases + ports)** | | |
| `pipeline.py` (`extract_all` orchestration) | `application/commands/extraction/extract_statement.py` | ExtractStatementCommand + Handler |
| `pipeline.py` (`extract` entry point) | `application/commands/extraction/extract_single.py` | Thin wrapper that calls extract_statement |
| `repair.py` | `application/commands/extraction/repair_statement.py` | RepairStatementHandler (called by extract) |
| `extract_summary.py` | `application/commands/extraction/extract_summary.py` | ExtractSummaryHandler (internal step) |
| `extract_transactions.py` | `application/commands/extraction/extract_transactions.py` | ExtractTransactionsHandler (internal step) |
| `extract_transactions_hybrid.py` | `application/commands/extraction/extract_transactions_hybrid.py` | Hybrid strategy |
| `chunking.py` | `application/services/chunking.py` | Stateless chunking logic |
| `enrich.py` | `application/commands/extraction/enrich_transactions.py` | EnrichTransactionsHandler |
| `segment.py` | `application/services/segmenter.py` | Stateless segmentation |
| `segment_llm.py` | `application/services/segmenter_llm.py` | LLM fallback segmenter |
| `prevalidate.py` | `application/commands/extraction/prevalidate_document.py` | PrevalidateDocumentHandler |
| `explain.py` | `application/queries/explain_anomaly.py` | ExplainAnomalyQuery + Handler |
| `diff_extractions.py` | `application/queries/diff_extractions.py` | DiffExtractionsQuery + Handler |
| `cost_estimate.py` | `application/queries/estimate_cost.py` | EstimateCostQuery + Handler |
| `prompt_lessons.py` | `application/services/lessons_store.py` | Cross-cutting service |
| `spend_cap.py` | `application/services/spend_guard.py` | Spend cap checking service |
| `tiers.py` | `application/config.py` + `domain/value_objects/tier.py` | Tier frozen dataclass → domain VO; registry → application config |
| — (new) | `application/errors.py` | ApplicationError hierarchy |
| — (new) | `application/common/list_result.py` | ListResult[T] generic |
| — (new) | `application/common/schemas.py` | Shared Pydantic response models (Statement, Transaction, etc.) |
| **Application ports (interfaces)** | | |
| `backends/base.py` (LLMBackend ABC) | `application/ports/llm_backend.py` | Protocol, not ABC |
| `cache.py` (StatementCache interface) | `application/ports/cache.py` | StatementCachePort Protocol |
| `cache_redis.py` (open_cache resolver) | stays in infrastructure | |
| `audit.py` (AuditLog interface) | `application/ports/audit_sink.py` | AuditSinkPort Protocol |
| `reviews.py` (ReviewStore interface) | `application/ports/review_store.py` | ReviewStorePort Protocol |
| — (new) | `application/ports/ocr_engine.py` | OcrEnginePort Protocol |
| — (new) | `application/ports/event_bus.py` | EventBusPort Protocol (SSE events) |
| — (new) | `application/ports/vendor_lookup.py` | VendorLookupPort Protocol |
| — (new) | `application/ports/telemetry_collector.py` | TelemetryCollectorPort Protocol |
| — (new) | `application/ports/__init__.py` | Re-exports all ports |
| **Infrastructure layer (concrete implementations)** | | |
| `backends/anthropic_backend.py` | `infrastructure/adapters/llm/anthropic_backend.py` | AnthropicLLMBackend |
| `backends/ollama_backend.py` | `infrastructure/adapters/llm/ollama_backend.py` | OllamaLLMBackend |
| `cache.py` (StatementCache impl) | `infrastructure/adapters/cache/sqlite_cache.py` | SqliteStatementCache |
| `cache_redis.py` (RedisCache, MemoryCache) | `infrastructure/adapters/cache/redis_cache.py`, `infrastructure/adapters/cache/memory_cache.py` | Split into separate files |
| `audit.py` (AuditLog impl) | `infrastructure/adapters/audit/sqlite_audit_sink.py` | SqliteAuditSink |
| `reviews.py` (ReviewStore impl) | `infrastructure/adapters/review/sqlite_review_store.py` | SqliteReviewStore |
| `ingest.py` (OCR + file reading) | `infrastructure/adapters/ocr/tesseract_engine.py`, `infrastructure/adapters/ocr/file_reader.py` | Split OCR from file-format detection |
| `ingest_vision.py` | `infrastructure/adapters/ocr/vision_engine.py` | VisionOcrEngine |
| `vendor_lookup.py` | `infrastructure/adapters/vendor/clearbit_lookup.py`, `infrastructure/adapters/vendor/seed_lookup.py` | Split Clearbit from seed file |
| `telemetry.py` | `infrastructure/adapters/telemetry/call_stats_collector.py` | CallStatsCollector |
| `tracing.py` | `infrastructure/adapters/telemetry/otel_tracer.py` | OpenTelemetry adapter |
| `warmup.py` | `infrastructure/adapters/llm/anthropic_warmup.py` | Part of Anthropic adapter |
| `tenant.py` | `infrastructure/adapters/tenant/thread_local_tenant.py` | Tenant context impl |
| `demo_replay.py` | `infrastructure/adapters/replay/demo_replay.py` | Demo replay adapter |
| **Presentation layer (transports)** | | |
| `api.py` | `presentation/api/http/v1/extraction/router.py`, `presentation/api/http/v1/extraction/schemas.py`, `presentation/api/http/v1/audit/router.py`, `presentation/api/http/v1/cache/router.py`, `presentation/api/http/v1/telemetry/router.py`, `presentation/api/http/v1/health/router.py`, `presentation/api/http/v1/review/router.py`, `presentation/api/http/v1/diff/router.py` | Split the monolithic api.py into domain-specific routers |
| `security_api.py` | `presentation/api/http/middleware/api_key.py`, `presentation/api/http/middleware/cors.py` | Middleware modules |
| `cli.py` | `presentation/cli/extract.py` | Click CLI |
| `ui_streamlit.py` | `presentation/streamlit/app.py` | Streamlit UI |
| `grpc/server.py` | `presentation/grpc/server.py` | gRPC transport |
| `grpc/client.py` | `presentation/grpc/client.py` | gRPC client |
| `grpc/extractor_pb2.py` | `presentation/grpc/extractor_pb2.py` | Generated |
| `grpc/extractor_pb2_grpc.py` | `presentation/grpc/extractor_pb2_grpc.py` | Generated |
| `export_excel.py` | `presentation/export/excel.py` | Excel output formatter |
| — (new) | `presentation/api/http/common/exc_handlers.py` | Exception → HTTP status mapping |
| — (new) | `presentation/api/http/common/schemas.py` | ErrorResponse, PaginationResponse |
| — (new) | `presentation/api/http/middleware/tenant.py` | X-Tenant-ID middleware |
| **Main layer (composition root)** | | |
| — (new) | `main/config/settings.py` | pydantic-settings: AppSettings, LLMSettings, CacheSettings, etc. |
| — (new) | `main/config/logging.py` | structlog configuration |
| — (new) | `main/di/container.py` | dishka container factory |
| — (new) | `main/di/providers/handlers.py` | HandlersProvider |
| — (new) | `main/di/providers/llm.py` | LLMProvider (backend selection) |
| — (new) | `main/di/providers/cache.py` | CacheProvider |
| — (new) | `main/di/providers/config.py` | ConfigProvider |
| — (new) | `main/di/providers/infrastructure.py` | Audit, Review, Telemetry, OCR providers |
| — (new) | `main/entrypoints/web/factory.py` | create_app() |
| — (new) | `main/entrypoints/web/__main__.py` | uvicorn runner |
| — (new) | `main/entrypoints/cli/factory.py` | CLI app factory |
| **Package root** | | |
| `__init__.py` | `__init__.py` | Re-export `extract`, `extract_all`, `Statement`, etc. |

---

## 2. New Protocol Files (Ports)

### `application/ports/llm_backend.py`

```python
from abc import abstractmethod
from typing import Protocol, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMBackendPort(Protocol):
    name: str

    @abstractmethod
    async def call_structured(
        self,
        system: str,
        user: str,
        response_model: type[T],
        *,
        role: str = "extract",
        max_retries: int = 6,
        cache_system: bool = True,
    ) -> T:
        raise NotImplementedError

    @abstractmethod
    async def call_vision(
        self,
        system: str,
        user: str,
        images: list,
        response_model: type[T],
        *,
        max_retries: int = 6,
    ) -> T:
        raise NotImplementedError

    @abstractmethod
    def supports_vision(self) -> bool:
        raise NotImplementedError
```

### `application/ports/cache.py`

```python
from abc import abstractmethod
from typing import Protocol


class StatementCachePort(Protocol):
    @abstractmethod
    async def get(self, key: str) -> "Statement | None":
        raise NotImplementedError

    @abstractmethod
    async def put(self, key: str, statement: "Statement") -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def clear(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def keys(self, limit: int = 200) -> list[dict]:
        raise NotImplementedError
```

### `application/ports/audit_sink.py`

```python
from abc import abstractmethod
from typing import Protocol


class AuditSinkPort(Protocol):
    @abstractmethod
    async def record(self, started_at: float, rec: "AuditRecord") -> int:
        raise NotImplementedError

    @abstractmethod
    async def recent(self, limit: int = 50) -> list[dict]:
        raise NotImplementedError
```

### `application/ports/ocr_engine.py`

```python
from abc import abstractmethod
from typing import Protocol
from pathlib import Path


class OcrEnginePort(Protocol):
    @abstractmethod
    async def extract_text(
        self,
        file_path: Path,
        *,
        log_event: "EventLogger | None" = None,
    ) -> str:
        raise NotImplementedError
```

### `application/ports/event_bus.py`

```python
from abc import abstractmethod
from typing import Protocol


class EventBusPort(Protocol):
    @abstractmethod
    async def emit(self, event_name: str, data: dict) -> None:
        raise NotImplementedError
```

### `application/ports/vendor_lookup.py`

```python
from abc import abstractmethod
from typing import Protocol


class VendorLookupPort(Protocol):
    @abstractmethod
    async def lookup(self, vendor_name: str) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    async def enrich_in_place(self, transactions: list[dict]) -> None:
        raise NotImplementedError
```

### `application/ports/review_store.py`

```python
from abc import abstractmethod
from typing import Protocol


class ReviewStorePort(Protocol):
    @abstractmethod
    async def record_decision(
        self, statement_key: str, tx_index: int, decision: str, reviewer: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_decisions(self, statement_key: str) -> list[dict]:
        raise NotImplementedError
```

### `application/ports/telemetry_collector.py`

```python
from abc import abstractmethod
from typing import Protocol


class TelemetryCollectorPort(Protocol):
    @abstractmethod
    def record(self, stats: "CallStats") -> None:
        raise NotImplementedError

    @abstractmethod
    def summary(self) -> dict:
        raise NotImplementedError
```

**Total: 8 ports.**

---

## 3. CQRS Command/Query Split

### Commands (write / side-effect operations)

| Command | File | Input | Output |
|---|---|---|---|
| `ExtractStatementCommand` | `application/commands/extraction/extract_statement.py` | pdf_path, txt_path, tier, options | list[StatementResult] |
| `ExtractSingleCommand` | `application/commands/extraction/extract_single.py` | pdf_path, txt_path, backend | dict (spec shape) |
| `PrevalidateDocumentCommand` | `application/commands/extraction/prevalidate_document.py` | text | bool (raises on failure) |
| `ExtractSummaryCommand` | `application/commands/extraction/extract_summary.py` | segment_text | SummaryResult |
| `ExtractTransactionsCommand` | `application/commands/extraction/extract_transactions.py` | segment_text, period | TransactionsResult |
| `RepairStatementCommand` | `application/commands/extraction/repair_statement.py` | text, summary, transactions, period | (transactions, reconciliation) |
| `EnrichTransactionsCommand` | `application/commands/extraction/enrich_transactions.py` | transactions | list[Transaction] |
| `BustCacheCommand` | `application/commands/cache/bust_cache.py` | key | bool |
| `ClearCacheCommand` | `application/commands/cache/clear_cache.py` | — | int (count) |
| `RecordReviewCommand` | `application/commands/review/record_review.py` | statement_key, tx_index, decision | None |

### Queries (read-only operations)

| Query | File | Input | Output |
|---|---|---|---|
| `GetExtractionResultQuery` | `application/queries/get_extraction_result.py` | job_id | StatementResult |
| `GetAuditLogQuery` | `application/queries/get_audit_log.py` | limit | list[AuditEntry] |
| `GetCacheKeysQuery` | `application/queries/get_cache_keys.py` | limit | list[CacheKeyEntry] |
| `GetTelemetryQuery` | `application/queries/get_telemetry.py` | — | TelemetrySummary |
| `GetTiersQuery` | `application/queries/get_tiers.py` | — | list[TierInfo] |
| `ExplainAnomalyQuery` | `application/queries/explain_anomaly.py` | anomaly, context | ExplanationResult |
| `DiffExtractionsQuery` | `application/queries/diff_extractions.py` | result_a, result_b | DiffResult |
| `EstimateCostQuery` | `application/queries/estimate_cost.py` | params | CostEstimate |
| `GetReviewsQuery` | `application/queries/get_reviews.py` | statement_key | list[ReviewDecision] |

**Total: 10 commands, 9 queries.**

---

## 4. Composition Root Sketch

### `main/di/container.py`

```python
from dishka import make_async_container
from dishka.integrations.fastapi import FastapiProvider

from dobs.main.config.settings import (
    AppSettings,
    AuditSettings,
    CacheSettings,
    LLMSettings,
    get_settings,
)
from dobs.main.di.providers.cache import CacheProvider
from dobs.main.di.providers.config import ConfigProvider
from dobs.main.di.providers.handlers import HandlersProvider
from dobs.main.di.providers.infrastructure import InfrastructureProvider
from dobs.main.di.providers.llm import LLMProvider


def get_providers():
    return (
        FastapiProvider(),
        ConfigProvider(),
        LLMProvider(),
        CacheProvider(),
        InfrastructureProvider(),
        HandlersProvider(),
    )


def create_container():
    settings = get_settings()
    context = {
        AppSettings: settings.app,
        LLMSettings: settings.llm,
        CacheSettings: settings.cache,
        AuditSettings: settings.audit,
    }
    return make_async_container(
        *get_providers(),
        context=context,
    )
```

### `main/di/providers/llm.py`

```python
from dishka import Provider, Scope, from_context, provide

from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.infrastructure.adapters.llm.anthropic_backend import AnthropicLLMBackend
from dobs.infrastructure.adapters.llm.ollama_backend import OllamaLLMBackend
from dobs.main.config.settings import LLMSettings


class LLMProvider(Provider):
    scope = Scope.APP

    settings = from_context(LLMSettings)

    @provide
    def llm_backend(self, settings: LLMSettings) -> LLMBackendPort:
        if settings.backend == "ollama":
            return OllamaLLMBackend(host=settings.ollama_host)
        return AnthropicLLMBackend(api_key=settings.anthropic_api_key)
```

### `main/di/providers/cache.py`

```python
from dishka import Provider, Scope, from_context, provide

from dobs.application.ports.cache import StatementCachePort
from dobs.infrastructure.adapters.cache.sqlite_cache import SqliteStatementCache
from dobs.infrastructure.adapters.cache.redis_cache import RedisStatementCache
from dobs.infrastructure.adapters.cache.memory_cache import MemoryStatementCache
from dobs.main.config.settings import CacheSettings


class CacheProvider(Provider):
    scope = Scope.APP

    settings = from_context(CacheSettings)

    @provide
    def cache(self, settings: CacheSettings) -> StatementCachePort:
        url = settings.url
        if url.startswith("redis://"):
            return RedisStatementCache(url)
        if url == "memory":
            return MemoryStatementCache()
        return SqliteStatementCache(url)
```

### `main/di/providers/handlers.py`

```python
from dishka import Provider, Scope, provide_all

from dobs.application.commands.extraction.extract_statement import ExtractStatementHandler
from dobs.application.commands.extraction.extract_single import ExtractSingleHandler
from dobs.application.commands.cache.bust_cache import BustCacheHandler
from dobs.application.commands.cache.clear_cache import ClearCacheHandler
from dobs.application.commands.review.record_review import RecordReviewHandler
from dobs.application.queries.get_audit_log import GetAuditLogHandler
from dobs.application.queries.get_cache_keys import GetCacheKeysHandler
from dobs.application.queries.get_telemetry import GetTelemetryHandler
from dobs.application.queries.get_tiers import GetTiersHandler
from dobs.application.queries.explain_anomaly import ExplainAnomalyHandler
from dobs.application.queries.diff_extractions import DiffExtractionsHandler
from dobs.application.queries.estimate_cost import EstimateCostHandler
from dobs.application.queries.get_reviews import GetReviewsHandler


class HandlersProvider(Provider):
    scope = Scope.REQUEST

    handlers = provide_all(
        ExtractStatementHandler,
        ExtractSingleHandler,
        BustCacheHandler,
        ClearCacheHandler,
        RecordReviewHandler,
        GetAuditLogHandler,
        GetCacheKeysHandler,
        GetTelemetryHandler,
        GetTiersHandler,
        ExplainAnomalyHandler,
        DiffExtractionsHandler,
        EstimateCostHandler,
        GetReviewsHandler,
    )
```

### `main/entrypoints/web/factory.py`

```python
from contextlib import asynccontextmanager

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from dobs.main.config.logging import configure_service_logging, get_logger
from dobs.main.config.settings import get_settings
from dobs.main.di.container import create_container
from dobs.presentation.api.http.common.exc_handlers import map_exc_handlers


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await app.state.dishka_container.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="dobs",
        debug=settings.app.debug,
        lifespan=lifespan,
    )
    configure_service_logging("web")
    container = create_container()
    setup_http_routes(app)
    map_exc_handlers(app)
    setup_dishka(container, app)
    setup_http_middlewares(app, settings)
    logger.info("App created")
    return app
```

---

## 5. Migration Order

### Phase 1: Domain (no I/O, no deps)

Create the domain layer first because it has zero external dependencies.
Everything else depends on it.

1. `domain/common/specification.py` — copy from eclipse verbatim.
2. `domain/entities/base.py` — Entity[OIDType] base.
3. `domain/value_objects/` — extract enums from current `schemas.py`:
   `LLMRole`, `TxCategory`, `AnomalyKind`, `Severity`, `Tier`.
4. `domain/entities/statement.py` — convert Statement from Pydantic to dataclass.
5. `domain/entities/audit_record.py` — from current `audit.py` AuditRecord.
6. `domain/services/` — move pure-logic modules:
   `reconcile.py`, `anomaly.py`, `forensic.py`, `continuity.py`,
   `recurring.py`, `parse_rows.py`, `security.py` (prompt sanitizer).
7. `domain/prompts.py` — move prompt constants.
8. `domain/errors.py` — create DomainError hierarchy.

**Validation:** All existing unit tests for reconcile, anomaly, forensic,
continuity, recurring, parse_rows, security should pass with only import
path changes.

### Phase 2: Ports (application/ports/)

Create the 8 Protocol interfaces. No implementation yet — just the
contracts.

1. `application/ports/llm_backend.py`
2. `application/ports/cache.py`
3. `application/ports/audit_sink.py`
4. `application/ports/ocr_engine.py`
5. `application/ports/event_bus.py`
6. `application/ports/vendor_lookup.py`
7. `application/ports/review_store.py`
8. `application/ports/telemetry_collector.py`
9. `application/ports/__init__.py` — re-exports.
10. `application/errors.py` — ApplicationError hierarchy.
11. `application/config.py` — frozen config dataclasses (ExtractionConfig,
    TierConfig).

**Validation:** mypy passes; no runtime tests yet for this layer.

### Phase 3: Infrastructure Adapters

Wrap existing implementation code behind the port interfaces.

1. `infrastructure/adapters/llm/anthropic_backend.py` — adapt current
   `backends/anthropic_backend.py`, make `call_structured` async (use
   `AsyncAnthropic`).
2. `infrastructure/adapters/llm/ollama_backend.py` — same treatment.
3. `infrastructure/adapters/cache/sqlite_cache.py` — wrap current
   `cache.py` StatementCache, make methods async via `asyncio.to_thread`.
4. `infrastructure/adapters/cache/redis_cache.py` — from `cache_redis.py`.
5. `infrastructure/adapters/cache/memory_cache.py` — from `cache_redis.py`.
6. `infrastructure/adapters/audit/sqlite_audit_sink.py` — from `audit.py`.
7. `infrastructure/adapters/ocr/tesseract_engine.py` — from `ingest.py`
   OCR portions.
8. `infrastructure/adapters/ocr/vision_engine.py` — from `ingest_vision.py`.
9. `infrastructure/adapters/ocr/file_reader.py` — from `ingest.py` file
   format detection portions.
10. `infrastructure/adapters/vendor/clearbit_lookup.py` — from
    `vendor_lookup.py`.
11. `infrastructure/adapters/review/sqlite_review_store.py` — from
    `reviews.py`.
12. `infrastructure/adapters/telemetry/call_stats_collector.py` — from
    `telemetry.py`.
13. `infrastructure/adapters/telemetry/otel_tracer.py` — from `tracing.py`.

**Validation:** Tests for cache_redis, audit, ingest, vendor_lookup pass
with import updates.

### Phase 4: Application (Commands + Queries + Handlers)

Build the use-case handlers that wire domain logic with ports.

1. `application/commands/extraction/extract_statement.py` — the main
   orchestrator, replaces `pipeline.py extract_all`. Injects: LLMBackendPort,
   StatementCachePort, AuditSinkPort, OcrEnginePort, EventBusPort,
   TelemetryCollectorPort, ExtractionConfig.
2. `application/commands/extraction/extract_single.py` — thin sync wrapper.
3. Internal step handlers (extract_summary, extract_transactions,
   repair_statement, enrich_transactions) — called by the main handler,
   not individually routed.
4. `application/commands/cache/bust_cache.py`, `clear_cache.py`.
5. `application/commands/review/record_review.py`.
6. All query handlers.
7. `application/services/` — chunking, segmenter, lessons_store,
   spend_guard.

**Validation:** `test_pipeline_mocked.py` passes (with mock ports).
`test_regression_golden.py` passes end-to-end.

### Phase 5: Presentation + Main (transports + DI wiring)

1. `main/config/settings.py` — pydantic-settings replacing scattered
   `os.getenv()` calls.
2. `main/config/logging.py` — structlog setup.
3. `main/di/` — dishka container and providers.
4. `presentation/api/http/` — split monolithic `api.py` into routers.
5. `presentation/cli/extract.py` — click CLI.
6. `presentation/api/http/common/exc_handlers.py` — error mapping.
7. `presentation/api/http/middleware/` — tenant, api_key, cors.
8. `main/entrypoints/web/factory.py` — create_app().
9. Package root `__init__.py` — re-export `extract`, `extract_all`.

**Validation:** Full test suite passes. `test_api_smoke.py` confirms
all endpoints work. The sync `extract()` entry point remains importable
from the package root.

---

## 6. Test Reorganisation

### Current → Target

| Current `tests/` file | Target `tests/` location | Layer |
|---|---|---|
| `test_reconcile.py` | `tests/domain/test_reconcile.py` | domain |
| `test_anomaly.py` | `tests/domain/test_anomaly.py` | domain |
| `test_forensic.py` | `tests/domain/test_forensic.py` | domain |
| `test_continuity.py` | `tests/domain/test_continuity.py` | domain |
| `test_recurring.py` | `tests/domain/test_recurring.py` | domain |
| `test_parse_rows.py` | `tests/domain/test_parse_rows.py` | domain |
| `test_security.py` | `tests/domain/test_prompt_sanitizer.py` | domain |
| `test_segment.py` | `tests/domain/test_segmenter.py` | domain |
| `test_chunking.py` | `tests/application/test_chunking.py` | application |
| `test_pipeline_mocked.py` | `tests/application/test_extract_statement.py` | application |
| `test_hybrid_extract.py` | `tests/application/test_extract_transactions_hybrid.py` | application |
| `test_lessons.py` | `tests/application/test_lessons_store.py` | application |
| `test_spend_cap.py` | `tests/application/test_spend_guard.py` | application |
| `test_tiers.py` | `tests/application/test_tiers.py` | application |
| `test_diff_extractions.py` | `tests/application/test_diff_extractions.py` | application |
| `test_cache_redis.py` | `tests/infrastructure/test_cache.py` | infrastructure |
| `test_audit.py` | `tests/infrastructure/test_audit_sink.py` | infrastructure |
| `test_ingest.py` | `tests/infrastructure/test_ocr_engine.py` | infrastructure |
| `test_vendor_lookup.py` | `tests/infrastructure/test_vendor_lookup.py` | infrastructure |
| `test_tracing.py` | `tests/infrastructure/test_otel_tracer.py` | infrastructure |
| `test_tenant.py` | `tests/infrastructure/test_tenant.py` | infrastructure |
| `test_export_excel.py` | `tests/presentation/test_export_excel.py` | presentation |
| `test_api_smoke.py` | `tests/presentation/test_api_smoke.py` | presentation |
| `test_regression_golden.py` | `tests/integration/test_regression_golden.py` | integration (cross-layer) |

### conftest.py fixtures

```
tests/
├── conftest.py              # shared fixtures: mock LLMBackendPort, event loop
├── domain/
│   └── conftest.py          # domain test data factories
├── application/
│   └── conftest.py          # mock port fixtures
├── infrastructure/
│   └── conftest.py          # temp DB paths, test cache
├── presentation/
│   └── conftest.py          # AsyncClient, test app factory
└── integration/
    └── conftest.py          # full pipeline fixtures
```

---

## 7. Target File Tree (Complete)

```
src/dobs/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── common/
│   │   ├── __init__.py
│   │   └── specification.py
│   ├── entities/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── statement.py
│   │   ├── audit_record.py
│   │   └── extraction_job.py
│   ├── value_objects/
│   │   ├── __init__.py
│   │   ├── llm_role.py
│   │   ├── tx_category.py
│   │   ├── anomaly_kind.py
│   │   ├── severity.py
│   │   └── tier.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── reconcile.py
│   │   ├── anomaly_detector.py
│   │   ├── forensic_detector.py
│   │   ├── continuity_auditor.py
│   │   ├── recurring_detector.py
│   │   ├── row_parser.py
│   │   └── prompt_sanitizer.py
│   ├── prompts.py
│   └── errors.py
├── application/
│   ├── __init__.py
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── extraction/
│   │   │   ├── __init__.py
│   │   │   ├── extract_statement.py
│   │   │   ├── extract_single.py
│   │   │   ├── extract_summary.py
│   │   │   ├── extract_transactions.py
│   │   │   ├── extract_transactions_hybrid.py
│   │   │   ├── repair_statement.py
│   │   │   ├── enrich_transactions.py
│   │   │   └── prevalidate_document.py
│   │   ├── cache/
│   │   │   ├── __init__.py
│   │   │   ├── bust_cache.py
│   │   │   └── clear_cache.py
│   │   └── review/
│   │       ├── __init__.py
│   │       └── record_review.py
│   ├── queries/
│   │   ├── __init__.py
│   │   ├── get_extraction_result.py
│   │   ├── get_audit_log.py
│   │   ├── get_cache_keys.py
│   │   ├── get_telemetry.py
│   │   ├── get_tiers.py
│   │   ├── explain_anomaly.py
│   │   ├── diff_extractions.py
│   │   ├── estimate_cost.py
│   │   └── get_reviews.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chunking.py
│   │   ├── segmenter.py
│   │   ├── segmenter_llm.py
│   │   ├── lessons_store.py
│   │   └── spend_guard.py
│   ├── common/
│   │   ├── __init__.py
│   │   ├── list_result.py
│   │   └── schemas.py
│   ├── ports/
│   │   ├── __init__.py
│   │   ├── llm_backend.py
│   │   ├── cache.py
│   │   ├── audit_sink.py
│   │   ├── ocr_engine.py
│   │   ├── event_bus.py
│   │   ├── vendor_lookup.py
│   │   ├── review_store.py
│   │   └── telemetry_collector.py
│   ├── config.py
│   └── errors.py
├── infrastructure/
│   ├── __init__.py
│   └── adapters/
│       ├── __init__.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── anthropic_backend.py
│       │   ├── anthropic_warmup.py
│       │   └── ollama_backend.py
│       ├── cache/
│       │   ├── __init__.py
│       │   ├── sqlite_cache.py
│       │   ├── redis_cache.py
│       │   └── memory_cache.py
│       ├── ocr/
│       │   ├── __init__.py
│       │   ├── tesseract_engine.py
│       │   ├── vision_engine.py
│       │   └── file_reader.py
│       ├── audit/
│       │   ├── __init__.py
│       │   └── sqlite_audit_sink.py
│       ├── vendor/
│       │   ├── __init__.py
│       │   ├── clearbit_lookup.py
│       │   └── seed_lookup.py
│       ├── review/
│       │   ├── __init__.py
│       │   └── sqlite_review_store.py
│       ├── telemetry/
│       │   ├── __init__.py
│       │   ├── call_stats_collector.py
│       │   └── otel_tracer.py
│       ├── tenant/
│       │   ├── __init__.py
│       │   └── thread_local_tenant.py
│       └── replay/
│           ├── __init__.py
│           └── demo_replay.py
├── presentation/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── http/
│   │       ├── __init__.py
│   │       ├── common/
│   │       │   ├── __init__.py
│   │       │   ├── exc_handlers.py
│   │       │   └── schemas.py
│   │       ├── middleware/
│   │       │   ├── __init__.py
│   │       │   ├── tenant.py
│   │       │   ├── api_key.py
│   │       │   └── cors.py
│   │       └── v1/
│   │           ├── __init__.py
│   │           ├── extraction/
│   │           │   ├── __init__.py
│   │           │   ├── router.py
│   │           │   └── schemas.py
│   │           ├── audit/
│   │           │   ├── __init__.py
│   │           │   └── router.py
│   │           ├── cache/
│   │           │   ├── __init__.py
│   │           │   └── router.py
│   │           ├── telemetry/
│   │           │   ├── __init__.py
│   │           │   └── router.py
│   │           ├── health/
│   │           │   ├── __init__.py
│   │           │   └── router.py
│   │           ├── review/
│   │           │   ├── __init__.py
│   │           │   └── router.py
│   │           └── diff/
│   │               ├── __init__.py
│   │               └── router.py
│   ├── cli/
│   │   ├── __init__.py
│   │   └── extract.py
│   ├── grpc/
│   │   ├── __init__.py
│   │   ├── server.py
│   │   ├── client.py
│   │   ├── extractor_pb2.py
│   │   └── extractor_pb2_grpc.py
│   ├── streamlit/
│   │   ├── __init__.py
│   │   └── app.py
│   └── export/
│       ├── __init__.py
│       └── excel.py
└── main/
    ├── __init__.py
    ├── config/
    │   ├── __init__.py
    │   ├── settings.py
    │   └── logging.py
    ├── di/
    │   ├── __init__.py
    │   ├── container.py
    │   └── providers/
    │       ├── __init__.py
    │       ├── handlers.py
    │       ├── config.py
    │       ├── llm.py
    │       ├── cache.py
    │       └── infrastructure.py
    └── entrypoints/
        ├── __init__.py
        ├── web/
        │   ├── __init__.py
        │   ├── factory.py
        │   └── __main__.py
        └── cli/
            ├── __init__.py
            ├── factory.py
            └── __main__.py
```
