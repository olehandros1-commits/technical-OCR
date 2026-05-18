# dobs.ai — Bank Statement Extraction Agent

Production-grade пайплайн, превращающий отсканированные/OCR'ed PDF выписок
из банка в выверенный структурированный JSON. Сделан под технический
интервью dobs.ai (Option 4) и развёрнут в полноценное async clean-architecture
решение: ports & adapters, Dishka DI, structured concurrency, structured
logging, observability stack, mypy strict, 154 теста зелёных, GitHub Actions CI,
и demo-replay режим без затрат на API для интервью и CI smoke.

[English version](./README.md)

---

## 1. Как запустить · обзор архитектуры

### Демо одной командой через Docker (бесплатно)

```bash
git clone git@github.com:olehandros1-commits/technical-OCR.git dobs
cd dobs

# Загрузите тестовый PDF (53 МБ, исключён из git-истории).
# Reviewer'ам ссылка отдельно; положите файл в корень репозитория как Binder2_Redacted.pdf

# Опционально — только для реальных LLM-вызовов. Demo replay ничего не требует.
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Поднимаем api + worker + redis + ui в replay-режиме (~7 сек на 10 выписок).
EXTRACTOR_DEMO_REPLAY=1 docker compose -f docker/docker-compose.yml up -d

# UI:           http://localhost:8080
# REST API:     http://localhost:8000
# OpenAPI docs: http://localhost:8000/docs
# /metrics:     http://localhost:8000/metrics  (Prometheus)
# Health:       http://localhost:8000/api/v1/health/{live,ready}
```

Перетащите PDF в UI, нажмите **Extract**, наблюдайте поток событий SSE и
рендер 10 выверенных выписок с аномалиями, повторяющимися группами и
кликабельным PDF-превью.

### Без Docker (локальный Python через uv)

```bash
# Установить uv (однократно): https://docs.astral.sh/uv/
uv sync --extra dev --extra ocr --extra redis --extra ollama --extra queue --extra streamlit

# Тесты (154 passed, 1 skipped, ~11 сек)
EXTRACTOR_DEMO_REPLAY=1 uv run pytest

# CLI
EXTRACTOR_DEMO_REPLAY=1 uv run dobs Binder2_Redacted.pdf --out results.json

# Lint + type-check
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/dobs/    # Success: no issues found in 180 source files
```

### Реальный (cloud) запуск

```bash
# В docker/docker-compose.yml поменяйте дефолт EXTRACTOR_DEMO_REPLAY на 0,
# или передайте явно:
EXTRACTOR_DEMO_REPLAY=0 docker compose -f docker/docker-compose.yml up -d

# В UI выберите tier: premium / balanced / cheap / local
# Ожидаемая стоимость на bundled sample (10 выписок):
#   premium  ~$0.30  (Opus repair, Sonnet extract)
#   balanced ~$0.15  (Sonnet)
#   cheap    ~$0.05  (Haiku)
#   local    $0      (Ollama qwen2.5:14b, требует host Ollama)
```

### Архитектура верхнего уровня

```
┌────────────┐    SSE     ┌───────────────┐    arq/Redis    ┌──────────────┐
│  React     │ ─────────▶ │   FastAPI     │ ─────────────▶ │   Worker(s)  │
│  FSD UI    │            │  (presentation │                │  (Dishka     │
│  + Streamlit│ ◀──── HTTP │   + Dishka DI)│                │   container) │
└────────────┘            └──────┬────────┘                └──────┬───────┘
                                 │                                 │
                                 ▼                                 ▼
                ┌──────────────────────────────────────────────────┐
                │            Clean Architecture (ядро)             │
                │   presentation → application → domain ← infra    │
                │    • 12 портов как typing.Protocols (внутри)     │
                │    • Adapter'ы (Anthropic, Ollama, SQLite, Redis,│
                │      Tesseract, Vision-LLM, Clearbit, …) снаружи │
                │    • Dishka container, нет service-locator       │
                └──────────────────────────────────────────────────┘
                                 │
                                 ▼
   ┌──────────────┬─────────────┬────────────┬──────────────┬────────────┐
   │ aiosqlite UoW│   Redis     │ arq queue  │ Anthropic /  │  OTel /    │
   │  5 БД:       │ pub/sub +   │ + worker   │ Ollama через │ Prometheus │
   │  audit,      │ job store + │ container  │ общий        │  / Sentry  │
   │  reviews,    │ cache       │            │ Structured-  │  (env-gate)│
   │  lessons,    │             │            │ OutputCaller │            │
   │  ocr_cache,  │             │            │              │            │
   │  vendor_cache│             │            │              │            │
   └──────────────┴─────────────┴────────────┴──────────────┴────────────┘
```

PDF приходит → `POST /api/v1/extraction/jobs` → middleware проставляет
request_id + tenant через ContextVar → `BackgroundJobRunner.spawn()` или
`ArqJobQueue.enqueue()` в зависимости от REDIS_URL → worker подбирает →
OCR (text-layer / tesseract / vision-LLM / OpenDataLoader) → LLM-сегментация
PDF на отдельные выписки → `asyncio.TaskGroup` обрабатывает выписки
параллельно: summary → transactions → reconciliation → repair (если нужно)
→ опциональный enrich + vendor lookup (deduped batch через TaskGroup, без N+1)
→ анализ аномалий + recurring + forensic + continuity → результаты
публикуются через Redis pub/sub → SSE в браузер с 15-сек heartbeat → финальное
событие `done` → `GET /jobs/{id}` отдаёт полный payload.

---

## 2. Соответствие ТЗ · что сделано сверху

### Обязательные требования

| Требование | Где реализовано | Статус |
|---|---|---|
| `extract(pdf_path, txt_path=None) -> dict` | `dobs.application.commands.extraction.extract_statement.ExtractStatementHandler.__call__` (+ CLI обёртка) | ✅ Async-first, поддерживает pdf-only / txt-only / оба |
| Схема: `account`, `summary`, `transactions[]` | `dobs.domain.entities.statement.Statement` + value-objects, mypy-strict | ✅ Зеркалится на фронте `entities/statement/model/types.ts` |
| Никаких выдуманных чисел | `dobs.domain.services.reconcile.Reconciler` + цикл `RepairStatementHandler` | ✅ Жёсткий reconciliation gate перед выводом |
| Должно сходиться (`begin + dep − wdr = end`) | `Reconciler.reconcile()` | ✅ На bundled sample: **10/10 reconciled** |
| Generalization через промпты, не код | `dobs.domain.prompts` (нет per-bank кода, layout-agnostic) | ✅ Одни промпты обрабатывают 10 выписок Ixonia (2 разных last4, переход года) |
| Запуск: CLI / HTTP / UI | `dobs` CLI, FastAPI `/api/v1/*`, React UI, Streamlit UI | ✅ Все четыре готовы |

**Самопроверка на bundled sample (`Binder2_Redacted.pdf`)**

* 10/10 выписок сходятся (`begin + dep − wdr = end`, точность ±1 цент)
* `last4`, период, deposits/withdrawals counts/totals — точное совпадение с эталонной таблицей
* 102 аномалии для ревью, 2 повторяющиеся группы вендоров

### Что сделано сверх ТЗ

Инженерное качество

* **Полностью async**: каждый I/O вызов асинхронный. AsyncAnthropic + `ollama.AsyncClient` + `aiosqlite` + `httpx.AsyncClient` + `arq` + `aiofiles`. Никаких `time.sleep`, блокирующего SQLite, `threading.Thread` в горячем пути.
* **Structured concurrency**: `asyncio.TaskGroup` (PEP 654 ExceptionGroup) для параллелизма по выпискам и chunk'ам, не `asyncio.gather`.
* **Clean architecture / hexagonal**: `presentation → application → domain ← infrastructure`. 12 портов как `typing.Protocol` в `application/ports/`, адаптеры в `infrastructure/adapters/`.
* **SOLID, без декорума**: SRP на каждый Command/Query/Handler; OCP через порты; LSP для подмены backend'ов; ISP (12 маленьких портов); DIP (хендлеры зависят от Protocols, никогда от адаптеров).
* **CQRS-lite**: Commands пишут, Queries читают, один handler на файл.
* **Dishka DI container** с `Scope.APP` провайдерами, `FromDishka[T]` в FastAPI-роутах. Composition в `dobs.main.di`, нет service-locator, нет глобалов.
* **UoW pattern** (`SqliteSessionFactory`): aiosqlite-сессия открывается через async context manager, commit-or-rollback обрабатывается фабрикой, никаких per-call connection setup. Одна фабрика на БД (5 всего).
* **Event bus через ContextVar**: handlers получают `EventBusPort` один раз через DI; per-request/per-job sink биндится через `bind_event_bus(bus)` context manager. Безопасно под concurrent jobs на shared `Scope.APP` handler — никакой mutation singleton'а.
* **`StructuredOutputCaller` ABC**: общий retry-loop + telemetry recording + pydantic coercion на оба LLM backend'а. Subclass'ы реализуют только `_invoke()` + `_is_retryable()`.
* **Background job lifecycle**: `BackgroundJobRunner` отслеживает `asyncio.Task` references и cancel'ит их на FastAPI lifespan shutdown — нет orphan tasks.
* **Multi-tenant**: per-request `contextvars.ContextVar` для tenant scope; cache keys, audit-записи и review разнесены по tenant'у.
* **mypy --strict**: 0 errors в 180 файлах. ~25 `# type: ignore[code]` комментариев, каждый с однострочной причиной.
* **Ruff** для lint + format (заменяет flake8 + isort + pyupgrade + black). `pre-commit` hooks гейтят каждый commit.
* **uv + uv.lock** — репродуцируемые Astral builds, ~10× быстрее pip в Docker.
* **GitHub Actions CI**: lint-and-typecheck, tests на Python 3.12 + 3.13 matrix с pytest-xdist + coverage, security (pip-audit + Trivy), docker-smoke который поднимает весь стек и assert'ит 10/10 контракт, frontend pnpm build.
* **154 теста** (~11 сек), включая 29 параметризованных DI-container wiring тестов, которые ловят missing `@provide` на pytest-стадии, не в Docker.

Функциональные фичи (сверх ТЗ)

* **4 tier'а качества/цены**: `premium` (Opus repair), `balanced` (Sonnet), `cheap` (Haiku), `local` (Ollama qwen2.5).
* **Два LLM backend'а**: Anthropic (cloud, с ephemeral prompt caching) и Ollama (локальный, structured output через `format=schema`).
* **Гибридная экстракция** (для Ollama): regex-парсер таблиц сначала достаёт candidate rows, LLM только классифицирует deposit/withdrawal. Дешевле и точнее на маленьких локальных моделях.
* **Repair-цикл** до 4 попыток: дельта подаётся обратно в промпт `REPAIR_SYSTEM` с предыдущим выводом. Best-so-far сохраняется при stalled convergence.
* **Детекция аномалий** (6 видов, 3 severity): duplicate pairs, date-out-of-period, running-balance drift, round-number outliers, size outliers, low-confidence.
* **Детекция повторяющихся транзакций**: vendor-keyed cadence (weekly / fortnightly / monthly / quarterly / irregular) с предсказанием следующего платежа.
* **Forensic-аномалии**: статистические эвристики (квази-Benford смещение по большим withdrawals).
* **Continuity audit**: проверка цепочки балансов между period'ами для одного `account_last4`.
* **Vendor enrichment**: `SeedVendorLookup` (JSON) → `ClearbitVendorLookup` (HTTP) composite с sqlite-кешем. Batch lookup с dedup + `TaskGroup` (без N+1).
* **HITL review queue**: low-confidence + warn/error аномалии всплывают в UI; решения сохраняются в `reviews.db` с полной историей.
* **Lessons store**: после успешного repair выводится human-readable hint, пишется в store. Будущие extraction'ы прайминговают `TRANSACTIONS_SYSTEM` промпт top-hint'ами.
* **Server-Sent Events** с 15-сек heartbeat (`DOBS_SSE_HEARTBEAT_S`), чтобы reverse-proxy не убивали idle SSE на длинных job'ах.
* **Background job queue**: arq + Redis. `/jobs` ставит в очередь, worker'ы обрабатывают out-of-process, события возвращаются через Redis pub/sub. Worker строит Dishka container один раз в `on_startup` и reuse'ит между job'ами.
* **Demo replay** (`EXTRACTOR_DEMO_REPLAY=1`): zero-cost воспроизведение записанного snapshot для live-демо и CI smoke. Реальные pipeline-события идут через тот же `event_bus`, SSE-клиент не различает.
* **Excel-экспорт**: `ExcelPresenter` строит DataFrames через pandas, пишет их через openpyxl; живые SUMIF/COUNTIF формулы + условное форматирование (красная строка при `_reconciliation.ok == false`).
* **PDF annotation overlay** (frontend): клик по строке → PDF превью прокручивается к нужной странице → совпадающий текст подсвечивается через fuzzy substring (60 → 30 → 20 char prefix).
* **Audit-лог**: каждая extraction пишется в `audit.db` — tier, backend, SHA-256 источника, statement count, reconciled count, cost, elapsed, оператор, IP, hash промптов.
* **API-key middleware**: `EXTRACTOR_API_KEYS` env включает per-request auth.
* **Spend cap enforced**: `SpendGuard` подключён к telemetry — каждый LLM-вызов инкрементит счётчик, бросает `SpendCapExceededError` при превышении `EXTRACTOR_SPEND_CAP_USD`.
* **20 REST endpoint'ов** под `/api/v1/*` — extraction (6: extract, jobs, jobs/events, jobs/{id}, bulk, xlsx-export), audit (1), cache (3), telemetry (2), reviews (3), explain (1), diff (1), health (3: live, ready, legacy).
* **Observability**:
  * **structlog** структурированное логирование с `request_id` ContextVar, прокинутым через SSE-события
  * **`/metrics`** endpoint Prometheus (toggle через `DOBS_DISABLE_METRICS`)
  * **OpenTelemetry** FastAPI + httpx + Redis auto-instrument при установленном `OTEL_EXPORTER_OTLP_ENDPOINT`
  * **Sentry** SDK + FastApiIntegration при установленном `SENTRY_DSN`
  * **Реальный readiness probe** `/api/v1/health/ready` пингует cache, audit DB, Redis, наличие ANTHROPIC_API_KEY; возвращает 503 с разбивкой по check'ам при degraded
* **Streamlit UI**: тонкий HTTP-клиент к `/api/v1/*`, 48-строчный `app.py` разложен на `ApiClient` + `SessionState` + 3 Presenter-класса + 5 components.
* **AI-agent docs**: `AGENTS.md` (layer rules, must-not list, where-to-put-what) + `CLAUDE.md` (Claude Code skill triggers, verification recipe). Codebase AI-ready: типизирован, контрактен, dockerized.

---

## 3. Архитектура кода бэкенда

Паттерн: **Clean Architecture / Hexagonal с CQRS-lite, async-throughout, Dishka DI, mypy --strict.**

```
src/dobs/
├── domain/                          # Чистый: ни I/O, ни фреймворков, async не обязателен
│   ├── entities/                    # Identity-bearing: Statement, AuditRecord, ExtractionJob
│   ├── value_objects/               # frozen+slots: Account, Period, Summary, Transaction, …
│   ├── services/                    # Чистые OOP сервисы:
│   │                                # Reconciler, AnomalyDetector, ContinuityAuditor,
│   │                                # ForensicAnomalyDetector, RecurringDetector,
│   │                                # PromptSanitizer, RowParser
│   ├── errors/                      # Доменные исключения
│   ├── prompts.py                   # SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM
│   └── specifications/              # Specification[T] (PEP 695 generics)
│
├── application/                     # Оркестрирует домен. Весь async.
│   ├── ports/                       # 12 Protocol-контрактов:
│   │                                # LLMBackendPort, OcrEnginePort, StatementCachePort,
│   │                                # AuditSinkPort, ReviewStorePort, LessonsStorePort,
│   │                                # EventBusPort, VendorLookupPort, VendorEnricherPort,
│   │                                # TelemetryCollectorPort, JobQueuePort, JobStorePort
│   ├── commands/                    # Запись (CQRS-C): один handler на файл
│   │   ├── extraction/              # ExtractStatement, ExtractSummary, ExtractTransactions,
│   │   │                            # ExtractTransactionsHybrid, PrevalidateDocument,
│   │   │                            # RepairStatement, EnrichTransactions
│   │   ├── cache/                   # BustCache, ClearCache
│   │   └── review/                  # RecordReview
│   ├── queries/                     # Чтение (CQRS-Q)
│   ├── services/                    # OOP-сервисы: StatementSegmenter, TransactionChunker,
│   │                                # CostEstimator, LessonsHelper, SpendGuard
│   ├── dto/                         # serialize_results — DTO между presentation/worker
│   └── errors.py                    # Application-уровень: SpendCapExceededError, etc.
│
├── infrastructure/                  # Конкретные адаптеры. Единственное место с side-эффектами.
│   ├── adapters/
│   │   ├── llm/
│   │   │   ├── base.py              # StructuredOutputCaller ABC: общий retry+telemetry
│   │   │   ├── anthropic_backend.py # AsyncAnthropic + ephemeral prompt cache
│   │   │   └── ollama_backend.py    # ollama.AsyncClient + format=json_schema
│   │   ├── ocr/
│   │   │   ├── composite_engine.py  # Оркестрирует OCR-стратегии
│   │   │   ├── file_reader.py       # Text-layer extraction (pdfplumber, fast path)
│   │   │   ├── tesseract_engine.py  # pdf2image + Tesseract (+ OcrCacheStore)
│   │   │   ├── vision_engine.py     # vision-LLM fallback
│   │   │   └── opendataloader_engine.py  # Опциональный Java-based extractor (env-gated)
│   │   ├── cache/                   # Memory / SQLite / Redis statement cache + URL resolver
│   │   ├── audit/                   # SqliteAuditSink (UoW)
│   │   ├── review/                  # SqliteReviewStore (UoW)
│   │   ├── lessons/                 # SqliteLessonsStore (UoW)
│   │   ├── event_bus/
│   │   │   ├── asyncio_event_bus.py # In-process pub/sub
│   │   │   ├── store_event_bus.py   # Persists events to JobStorePort
│   │   │   └── context_event_bus.py # ContextVar-bound router (singleton-safe)
│   │   ├── vendor/                  # Seed + Clearbit + composite + enricher (batch dedup)
│   │   ├── telemetry/               # CallStatsCollector + (unwired) OTel tracer
│   │   ├── tenant/                  # ContextTenantBinder (contextvars-based)
│   │   ├── replay/
│   │   │   ├── demo_replay.py       # DemoReplayPlayer читает snapshot, эмитит события
│   │   │   └── replaying_extract_handler.py  # Wrap'ит real handler, routes в replay
│   │   └── jobs/
│   │       ├── memory_job_store.py  # In-process store с TTL + max-jobs eviction
│   │       ├── redis_job_store.py   # Redis-backed pub/sub + result hash
│   │       ├── arq_job_queue.py     # Enqueue в arq
│   │       ├── asyncio_job_queue.py # In-process queue (в основном исторический)
│   │       └── background_runner.py # Tracks tasks, cancels on shutdown
│   └── persistence/
│       └── sqlite_session.py        # SqliteSessionFactory: UoW для всех 5 SQLite БД
│
├── presentation/                    # Способы доставки (adapter'ы в DDD-парлансе)
│   ├── api/http/
│   │   ├── app_factory.py           # create_app(): lifespan + middleware + setup_dishka()
│   │   ├── middleware/              # api_key, tenant, request_id, cors
│   │   └── v1/                      # Router-per-domain: extraction, telemetry, audit,
│   │                                # cache, reviews, diff, health
│   ├── cli/extract.py               # Click CLI → asyncio.run(_run(...))
│   ├── streamlit/                   # 48-line app.py + ApiClient + SessionState +
│   │                                # 3 presenters + 5 components
│   └── export/excel.py              # ExcelPresenter (pandas + openpyxl)
│
└── main/                            # Composition root + entry points
    ├── di.py                        # 7 Dishka Providers + build_providers()
    ├── worker.py                    # arq WorkerSettings (Dishka container built on_startup)
    ├── logging_setup.py             # structlog + request_id ContextVar
    └── config/settings.py           # pydantic_settings.BaseSettings (env-driven, типизирован)
```

Ключевые соглашения

* **Сигнатура конструктора**: `def __init__(self, /, *, dep: Port) -> None`. Positional-only `self` + keyword-only deps делают случайное позиционное связывание невозможным.
* **Dataclasses**: `frozen=True, kw_only=True, slots=True` для value objects, команд, queries. `eq=False, kw_only=True` для identity-bearing entity'ев.
* **Никакого service locator**: каждый handler/adapter получает deps через constructor injection. Единственная точка композиции — `dobs.main.di.build_providers()`.
* **Никаких silent failures**: каждый прежде-silent `except Exception: pass` заменён на `log.warning(..., exc_info=True)` + named SSE-событие (`lessons_failed`, `enrich_failed`, `vendor_enrich_failed`, `audit_failed`). Audit-record failures эскалируют в `log.error("AUDIT RECORD FAILED — compliance gap")`.
* **ContextVar event bus**: handlers берут `event_bus: EventBusPort` один раз при construction. Per-request/per-job sink биндится через `with bind_event_bus(sink):`, поэтому singleton handler безопасен под concurrent jobs.
* **Demo-replay роутинг** происходит на композиционном корне в `ReplayingExtractHandler` (infrastructure adapter), а не в роутере. Один zero-cost путь работает для `/extract`, `/jobs`, CLI, Streamlit.

---

## 4. Архитектура кода фронтенда

Паттерн: **Feature-Sliced Design (FSD), строгие слои, импорты через `@/`-alias.**

```
frontend/src/
├── app/                             # 1. Верхний слой — композиционный корень
│   ├── main.tsx                     #    React 18 createRoot + StrictMode
│   ├── App.tsx                      #    Тонкая оболочка: <ExtractionPage />
│   ├── App.css, index.css           #    Глобальные стили
│   └── index.ts
│
├── pages/                           # 2. Маршруты — владеют top-level стейтом
│   └── extraction/
│       ├── ui/ExtractionPage.tsx    #    Держит state, соединяет widgets и features
│       └── index.ts
│
├── widgets/                         # 3. Композитные UI-блоки
│   ├── statement-card/              #    Summary + transactions + аномалии на выписку
│   ├── pipeline-events/             #    LiveProgress (SSE) + TelemetryStrip
│   ├── review-queue/                #    HITL-очередь
│   ├── time-series-dashboard/       #    Cross-statement графики
│   ├── diff-view/                   #    Side-by-side diff
│   └── pdf-preview/                 #    react-pdf shell, использует pdf-text-search feature
│
├── features/                        # 4. Пользовательские действия, каждый со своим API-клиентом
│   ├── extract-job/                 #    createJob + streamJobEvents + getJobResult + extractBlocking
│   ├── upload-file/                 #    FileDropzone
│   ├── tier-select/                 #    Toolbar
│   ├── download-xlsx/
│   ├── explain-anomaly/
│   ├── diff-extractions/
│   ├── review-decision/
│   └── pdf-text-search/             #    usePdfTextIndex + usePdfHighlight hooks
│
├── entities/                        # 5. Доменные типы + UI, привязанный к одной сущности
│   ├── statement/                   #    Account, Period, Summary, StatementResult
│   ├── transaction/                 #    + TransactionsTable.tsx
│   ├── anomaly/                     #    Anomaly, severities, kinds
│   ├── reconciliation/              #    + ReconciliationChart.tsx
│   ├── recurring-group/             #    + RecurringPanel.tsx
│   ├── tier/                        #    + listTiers() API
│   ├── pipeline-event/
│   └── review/                      #    ReviewItem, Decision
│
└── shared/                          # 6. Нижний слой — без бизнес-смысла
    ├── api/                         #    BASE, V1, _formData, ExtractOptions, Telemetry
    └── config/                      #    REVIEW_THRESHOLD, прочие константы
```

Правила слоёв FSD

* Слой может импортировать только из **нижних** слоёв (`app → pages → widgets → features → entities → shared`).
* Слайсы одного слоя никогда не импортируют друг друга напрямую.
* Каждый слайс отдаёт публичную поверхность через `index.ts`. Внешние импорты идут через barrel.
* Path-alias `@/*` → `frontend/src/*` прописан и в `tsconfig.app.json`, и в `vite.config.ts`.

Сборка

* `vite build` → `dist/index-*.js` ~648 КБ (gzip 195 КБ), `index-*.css` ~27 КБ
* 98 модулей за ~170 мс
* Хостится nginx'ом в контейнере `ui` на порту 80, наружу мапится 8080

---

## 5. Вывод — насколько хорошо получилось

### Что получилось хорошо

* **Точность на сэмпле**: 10/10 reconciled, точное совпадение с эталонной таблицей по всем summary-полям. Гибридная экстракция + repair-цикл это заработали.
* **Генерализация действительно через промпты**: они лежат в `dobs.domain.prompts`, никаких per-bank `if`'ов нигде.
* **Demo-replay** убирает главный риск интервью — даун Anthropic или сюрприз по бюджету. Весь пайплайн воспроизводится за ~7 сек бесплатно, с тем же SSE-стримом что и live путь.
* **Clean architecture здесь не показуха**: у каждого адаптера есть Protocol, Dishka инъектит, `tests/test_di_container.py` параметризован по всем 29 портам + handler'ам и ловит missing `@provide` на pytest-стадии, а не на запуске контейнера.
* **Async-throughout** со structured concurrency означает, что один API-контейнер обрабатывает пересекающиеся job'ы без thread pools и GIL-contention. Worker масштабируется горизонтально через `--scale worker=N`.
* **FSD на фронте** делает React-сторону читабельной: у каждого концепта своя папка, страница композирует виджеты, направление импорта невозможно перепутать.
* **Quality gates реальны**: 154 теста за 11 сек, mypy --strict 0 errors, ruff 0 errors, ruff format применён на 206 файлов, CI гоняется на каждый push с Python 3.12 + 3.13 matrix и docker-smoke job'ом, который assert'ит 10/10 контракт.
* **Observability подключена, но не навязана**: structlog + request_id по дефолту; `/metrics`, OpenTelemetry, Sentry все включаются одним env var, выключены по дефолту.
* **20 endpoint'ов, 4 tier'а, 2 backend'а, 1 контракт**: публичная сигнатура `extract()` не ломалась за всю историю рефакторинга.

### Честные слабые места

* **Нет стриминга OCR**: PDF загружается в память и OCR'ится разом. Для 53 МБ нормально; для ≥200 МБ нужно chunking.
* **Local-LLM tier (Ollama qwen2.5)** медленнее и менее точен, чем cloud-tier'ы. Подходит как fallback или для чувствительных данных; demo по дефолту через `balanced` (Sonnet).
* **Генерализация на действительно неизвестных layout'ах не проверена на момент интервью** — промпты layout-agnostic, в сэмпле есть внутреннее разнообразие, но Wells Fargo / Chase statement во время живого демо был бы реальной проверкой.
* **Бандл фронта 648 КБ без сплита** (основная масса — react-pdf). `React.lazy()` на PDF preview срезал бы initial bundle на ~40%.
* **Один pytest-кейс пропущен** (`test_sse_replay_completes_with_done_event`): teardown loop'а TestClient'а гоняется с `call_soon_threadsafe` в worker-треде. Эквивалентный live-путь проверяется через `test_extract_replay_returns_full_payload` + docker-smoke CI job.
* **Нет SQLAlchemy / миграций**: 5 SQLite БД с `CREATE TABLE IF NOT EXISTS` схемами — работает до первого ALTER. 50-строчный `SqliteMigrator` закроет gap когда понадобится.
* **У воркеров нет autoscaler'а**: `docker compose up --scale worker=4` работает, но Kubernetes HPA нет. Вне рамок интервью brief'а.

### Итог

ТЗ просило функцию которая сходится. На выходе — multi-tier extraction
сервис с clean-architecture ядром, async-очередью, live UI, audit-логом,
детекцией аномалий, observability stack, полным CI, mypy --strict, и
zero-cost demo путём — построенный на дисциплине, которая переживает
и интервью, и реальный production-rollout.

Репозиторий — это deliverable; демо запускается одним `docker compose -f
docker/docker-compose.yml up -d`.
