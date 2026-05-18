# dobs.ai — Bank Statement Extraction Agent

Production-grade пайплайн, превращающий отсканированные/OCR'ed PDF выписок
из банка в выверенный структурированный JSON. Сделан под технический
интервью dobs.ai (Option 4) и развёрнут в полноценное clean-architecture
решение с async-бэкендом, FSD-фронтендом, фоновыми воркерами, аудит-логом,
детекцией аномалий, аналитикой повторяющихся транзакций и demo-replay
режимом без затрат на API.

[English version](./README.md)

---

## 1. Как запустить · обзор архитектуры

### Демо в один шаг через Docker (бесплатно)

```bash
git clone git@github.com:olehandros1-commits/technical-OCR.git dobs
cd dobs

# Опционально — нужно только для реальных LLM-вызовов. Для demo не требуется.
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Поднимаем api + worker + redis + ui в режиме replay (~7 сек на 10 выписок).
EXTRACTOR_DEMO_REPLAY=1 docker compose -f docker/docker-compose.yml up -d

# UI:           http://localhost:8080
# REST API:     http://localhost:8000
# OpenAPI docs: http://localhost:8000/docs
```

Перетащите `Binder2_Redacted.pdf` из корня репозитория в UI, нажмите
**Extract**, наблюдайте поток событий SSE и 10 выверенных выписок с аномалиями,
повторяющимися группами и кликабельным PDF-превью.

### Без Docker (локальный Python)

```bash
pip install -e ".[dev,redis,queue,streamlit]"
EXTRACTOR_DEMO_REPLAY=1 dobs Binder2_Redacted.pdf --out results.json
pytest    # 121 passed, 1 skipped
```

### Реальный (cloud) запуск

```bash
unset EXTRACTOR_DEMO_REPLAY        # снимаем защиту от расходов
docker compose -f docker/docker-compose.yml up -d
# В UI выберите tier: premium / balanced / cheap / local
```

### Архитектура верхнего уровня

```
┌─────────────┐    SSE     ┌──────────────┐    arq/Redis    ┌──────────────┐
│   React +   │ ─────────▶ │   FastAPI    │ ─────────────▶ │   Worker(s)  │
│   FSD UI    │            │ (presentation)│                │ (composition │
│             │ ◀───── HTTP│              │                │  root + DI)  │
└─────────────┘            └──────┬───────┘                └──────┬───────┘
                                  │                                │
                                  ▼                                ▼
                     ┌──────────────────────────────────────────────────┐
                     │           Clean Architecture (ядро)              │
                     │  presentation → application → domain ← infra     │
                     │   • Ports (Protocols) внутри                     │
                     │   • Adapters (Anthropic, Ollama, SQLite, Redis,  │
                     │     Tesseract, Vision-LLM, Clearbit) снаружи     │
                     └──────────────────────────────────────────────────┘
                                  │
                                  ▼
        ┌────────────┬─────────────┬────────────┬────────────┐
        │ aiosqlite  │   Redis     │  arq queue │  Anthropic │
        │ (cache,    │ (pub/sub,   │  (jobs)    │  / Ollama  │
        │  audit,    │  job store) │            │  (LLM)     │
        │  reviews,  │             │            │            │
        │  lessons)  │             │            │            │
        └────────────┴─────────────┴────────────┴────────────┘
```

Пользователь приходит с PDF → загружает через `/api/v1/extraction/jobs` →
ставится в очередь arq → воркер-контейнер забирает джобу → OCR (skip /
tesseract / vision-LLM) → LLM-сегментация PDF на отдельные выписки → каждая
выписка обрабатывается параллельно: summary → transactions → reconciliation
→ repair (если нужно) → опциональный enrich → анализ аномалий + повторяющихся
платежей + forensic + continuity → результаты возвращаются через Redis
pub/sub → SSE летит в браузер → финальное событие `done` триггерит
`GET /jobs/{id}` для полного payload.

---

## 2. Соответствие ТЗ · что сделано сверху

### Обязательные требования (из ТЗ)

| Требование | Где реализовано | Статус |
|---|---|---|
| `extract(pdf_path, txt_path=None) -> dict` | `dobs.application.commands.extraction.extract_statement` (+ CLI-обёртка `dobs.presentation.cli.extract`) | ✅ Стабильный API, async-first, sync CLI-мост |
| Схема: `account`, `summary`, `transactions[]` | `dobs.domain.entities.statement.Statement` + value objects | ✅ Зеркалится на фронте в `entities/statement/model/types.ts` |
| Никаких выдуманных чисел | `dobs.domain.services.reconcile` + цикл `repair_statement` | ✅ Reconciliation-гейт перед выводом |
| Должно сходиться (`begin + dep − wdr = end`) | `dobs.domain.services.reconcile` | ✅ На сэмпле: **10/10 reconciled** |
| Generalization через промпты, не код | `dobs.domain.prompts` (никаких per-bank условий) | ✅ Одни и те же промпты обрабатывают все 10 выписок Ixonia; рассчитано на незнакомые банки |
| Запуск: CLI / HTTP / UI | CLI `dobs`, FastAPI `/api/v1/*`, React UI, Streamlit UI | ✅ Все четыре готовы |

**Самопроверка на сэмпле (`Binder2_Redacted.pdf`)**

* 10/10 выписок сходятся (`begin + dep − wdr = end`, точность ±1 цент)
* `last4`, период, deposits/withdrawals counts/totals — точно совпадают с эталонной таблицей
* 102 аномалии для ревью, 2 повторяющиеся группы вендоров

### Что сделано сверх ТЗ

Инженерное качество

* **Полностью async**: каждый I/O вызов асинхронный. AsyncAnthropic + `ollama.AsyncClient` + `aiosqlite` + `httpx.AsyncClient` + `arq`. Нет `time.sleep`, блокирующего SQLite, `threading.Thread` в горячем пути.
* **Clean architecture / гексагональная**: `presentation → application → domain ← infrastructure`. Порты определены как `typing.Protocol` в `application/ports/`, адаптеры в `infrastructure/adapters/`.
* **SOLID, без декорума**: SRP на каждый Command/Query/Handler; OCP через порты; LSP для подмены backend'ов; ISP (10 маленьких портов вместо одного «god-port»); DIP (хендлеры зависят от Protocols).
* **CQRS-lite**: Commands пишут, Queries читают, каждый handler в своём файле.
* **DI через композиционный корень**: `dobs.main.composition_root.Container` инъектит каждый порт через конструктор. Никаких service-locator, никаких глобалов.
* **Multi-tenant**: per-request `contextvars.ContextVar` для tenant scope; ключи кеша, аудит и review разнесены по tenant'у.
* **121 тест** (115 unit + 6 на очередь), `asyncio_mode="auto"`, гоняются за 11 секунд.

Функциональные фичи (сверх ТЗ)

* **4 tier'а качества/цены**: `premium` (Opus repair), `balanced` (Sonnet), `cheap` (Haiku), `local` (Ollama qwen2.5). Каждый tier выбирает свою тройку моделей + OCR-режим + дефолты enrichment.
* **Два LLM-backend'а**: Anthropic (cloud) и Ollama (локальный через `host.docker.internal`).
* **Гибридная экстракция**: сначала детерминированный парсер таблиц, потом LLM добивает строки, которые парсер не смог. Экономит и деньги, и латенси.
* **Repair-цикл**: если reconciliation не прошёл, дельта подаётся в промпт `REPAIR_SYSTEM` вместе с предыдущим выводом, чтобы LLM прицельно исправил.
* **Детекция аномалий** (6 видов, 3 severity): дублирующиеся пары, дата вне периода, дрейф running balance, round-number выбросы, size outliers, low-confidence.
* **Детекция повторяющихся транзакций**: анализ каденции по vendor key (weekly / fortnightly / monthly / quarterly / irregular) с предсказанием следующего платежа.
* **Forensic-аномалии**: статистические эвристики (квази-Benford смещение, повторяющиеся суммы).
* **Continuity audit**: проверка цепочки балансов между выписками по одному `account_last4`.
* **Vendor enrichment**: seed-lookup + Clearbit (логотипы), composite-обёртка с кешем.
* **HITL review queue**: low-confidence + warn/error аномалии всплывают в UI; решения ревьюера сохраняются в `reviews.db` с полным audit-trail.
* **Lessons store**: провалившиеся экстракции логируются вместе с паттерном repair'а; будущие похожие случаи можно прайминговать.
* **Server-Sent Events**: live progress пайплайна (`ingest_start` → `segment_done_all` → пер-сегмент `summary_done` / `transactions_done` / `reconcile` / `segment_done` → `done`).
* **Background job queue**: arq + Redis с одним или несколькими worker-контейнерами. `/jobs` ставит в очередь, воркеры обрабатывают, события возвращаются через Redis pub/sub.
* **Demo replay** (`EXTRACTOR_DEMO_REPLAY=1`): zero-cost воспроизведение снэпшота для live-демо и CI smoke-тестов. Реалистичные события с задержками.
* **Excel-экспорт**: многолистовая книга с живыми SUMIF-формулами, условным форматированием, листом continuity.
* **PDF annotation overlay**: клик по транзакции в UI прокручивает PDF до нужной страницы и подсвечивает совпадающий текстовый span (fuzzy-search через text layer `pdfjs`).
* **Audit-лог**: каждая экстракция пишется в `audit.db` — tier, backend, SHA-256 источника, statement count, reconciled count, стоимость, время, оператор, IP, hash промптов.
* **API-key middleware**: `EXTRACTOR_API_KEYS` env включает per-request auth.
* **Spend cap**: жёсткий потолок расходов на процесс.
* **Telemetry**: tokens in/out, cache reads/writes, elapsed, cost — отображается в UI и доступно через `/api/v1/telemetry`.
* **`diff` endpoint**: структурное сравнение двух экстракций для регрессии при изменении промптов.
* **`explain` endpoint**: LLM объясняет конкретную аномалию текстом.
* **17 REST endpoint'ов** под `/api/v1/*` — extraction, jobs, audit, cache, telemetry, tiers, reviews, explain, diff, export, health.
* **Streamlit UI** как альтернативный тонкий клиент (помимо React).

---

## 3. Архитектура кода бэкенда

Паттерн: **Clean Architecture / Hexagonal с CQRS-lite, полностью async, со строгим SOLID.**

```
src/dobs/
├── domain/                       # Чистый слой: ни I/O, ни фреймворков, ни обязательного async
│   ├── entities/                 # Объекты с identity: Statement, AuditRecord
│   ├── value_objects/            # frozen+slots: Account, Period, Summary, Transaction
│   ├── services/                 # Доменная логика: reconcile, anomaly_detector,
│   │                             # continuity_auditor, forensic_detector, recurring_detector,
│   │                             # prompt_sanitizer
│   ├── errors/                   # Доменные исключения
│   ├── prompts.py                # SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM
│   └── specifications/           # Specification[T] для предикатов
│
├── application/                  # Оркестрирует домен. Весь async.
│   ├── ports/                    # Контракты-Protocol (10):
│   │                             # LLMBackendPort, OcrEnginePort, StatementCachePort,
│   │                             # AuditSinkPort, ReviewStorePort, EventBusPort,
│   │                             # VendorLookupPort, TelemetryCollectorPort,
│   │                             # LessonsStorePort, JobQueuePort, JobStorePort
│   ├── commands/                 # Запись (CQRS-C):
│   │   ├── extraction/           # ExtractStatement, ExtractSummary, ExtractTransactions,
│   │   │                         # ExtractTransactionsHybrid, PrevalidateDocument,
│   │   │                         # RepairStatement, EnrichTransactions
│   │   ├── cache/                # BustCache, ClearCache
│   │   └── review/               # RecordReview
│   ├── queries/                  # Чтение (CQRS-Q):
│   │                             # DiffExtractions, EstimateCost, ExplainAnomaly,
│   │                             # GetAuditLog, GetCacheKeys, GetReviews,
│   │                             # GetTelemetry, GetTiers
│   └── services/                 # Утилиты между хендлерами:
│                                 # segmenter, chunking, spend_guard, cost_estimate,
│                                 # lessons_helpers
│
├── infrastructure/               # Конкретные адаптеры. Единственное место с side-эффектами.
│   └── adapters/
│       ├── llm/                  # AnthropicLLMBackend (AsyncAnthropic), OllamaLLMBackend
│       ├── ocr/                  # FileReader, TesseractOcrEngine, VisionOcrEngine,
│       │                         # CompositeOcrEngine
│       ├── cache/                # MemoryStatementCache, SqliteStatementCache,
│       │                         # RedisStatementCache, resolver (URL → backend)
│       ├── audit/                # SqliteAuditSink (aiosqlite)
│       ├── review/               # SqliteReviewStore
│       ├── lessons/              # SqliteLessonsStore
│       ├── event_bus/            # AsyncioEventBus (in-process), StoreEventBus (Redis pub/sub)
│       ├── vendor/               # SeedVendorLookup, ClearbitVendorLookup, CompositeVendorLookup
│       ├── telemetry/            # CallStatsCollector
│       ├── tenant/               # ContextTenantBinder (на contextvars)
│       ├── replay/               # DemoReplayPlayer (zero-cost demo)
│       └── jobs/                 # MemoryJobStore, RedisJobStore, ArqJobQueue,
│                                 # AsyncioJobQueue
│
├── presentation/                 # Адаптеры под способы доставки
│   ├── api/http/
│   │   ├── app_factory.py        # create_app() — здесь делается dependency_overrides
│   │   ├── middleware/           # api_key, tenant, request_id, cors
│   │   └── v1/                   # Роутер на домен: extraction, telemetry, audit,
│   │                             # cache, reviews, diff, health
│   ├── cli/extract.py            # Click CLI → asyncio.run(_run(...))
│   ├── streamlit/app.py          # Тонкий HTTP-клиент к /api/v1/*
│   └── export/excel.py           # openpyxl-книга с живыми формулами
│
└── main/                         # Композиционный корень
    ├── composition_root.py       # Container — ленивые синглтоны, DI через конструктор,
    │                             # _ReplayingExtractHandler-обёртка,
    │                             # адаптер-обёртки для расхождений имён методов
    ├── config/settings.py        # AppSettings (читает env, никаких kwargs)
    └── worker.py                 # arq WorkerSettings: dobs.main.worker
```

Ключевые соглашения

* **Сигнатура конструктора**: `def __init__(self, /, *, dep: Port) -> None`. Positional-only `self` + keyword-only deps исключают случайное позиционное связывание.
* **Dataclasses**: `frozen=True, kw_only=True, slots=True` для value object'ов и команд. `eq=False, kw_only=True` для entity'ев (нужен `oid: str` для identity).
* **Lazy container**: каждый порт создаётся один раз при первом обращении, кешируется на контейнере. Синглтоны по lifetime, а не по статическому состоянию.
* **Никакого service locator**: `app_factory.create_app()` API проставляет `dependency_overrides` для роутеров FastAPI; CLI собирает свой контейнер; воркер — свой. Никакого глобального контейнера.
* **Replay handler**: `_ReplayingExtractHandler` оборачивает реальный. При `EXTRACTOR_DEMO_REPLAY=1` идёт в `DemoReplayPlayer.replay()`, который форвардит события через тот же `event_bus`, так что SSE-клиент не отличает реальный путь от replay.
* **Replay завязан на композиционный корень**, а не на роутер. Это значит, что zero-cost путь работает и для синхронного `/extract`, и для async `/jobs`, и для CLI, и для Streamlit.

---

## 4. Архитектура кода фронтенда

Паттерн: **Feature-Sliced Design (FSD), строгие слои, импорты через `@/`-alias.**

```
frontend/src/
├── app/                          # 1. Верхний слой — композиционный корень
│   ├── main.tsx                  #    React 18 createRoot + StrictMode
│   ├── App.tsx                   #    Тонкая оболочка: <ExtractionPage />
│   ├── App.css, index.css        #    Глобальные стили
│   └── index.ts
│
├── pages/                        # 2. Маршруты — владеют page-level стейтом
│   └── extraction/
│       ├── ui/ExtractionPage.tsx #    Держит top-level state, соединяет widgets и features
│       └── index.ts
│
├── widgets/                      # 3. Композитные UI-блоки
│   ├── statement-card/           #    Summary + transactions + аномалии на выписку
│   ├── pipeline-events/          #    LiveProgress (SSE) + TelemetryStrip
│   ├── review-queue/             #    HITL-очередь
│   ├── time-series-dashboard/    #    Графики между выписками
│   ├── diff-view/                #    Side-by-side diff двух экстракций
│   └── pdf-preview/              #    react-pdf с подсветкой при клике
│
├── features/                     # 4. Пользовательские действия, у каждого свой API-клиент
│   ├── extract-job/              #    createJob + streamJobEvents + getJobResult
│   ├── upload-file/              #    FileDropzone
│   ├── tier-select/              #    Toolbar: tier/backend/OCR/enrich/parallel
│   ├── download-xlsx/
│   ├── explain-anomaly/
│   ├── diff-extractions/
│   └── review-decision/
│
├── entities/                     # 5. Доменные типы + UI, привязанный к одной сущности
│   ├── statement/                #    Account, Period, Summary, StatementResult
│   ├── transaction/              #    + TransactionsTable.tsx
│   ├── anomaly/                  #    Anomaly, severities, kinds
│   ├── reconciliation/           #    + ReconciliationChart.tsx
│   ├── recurring-group/          #    + RecurringPanel.tsx
│   ├── tier/                     #    + listTiers() API
│   ├── pipeline-event/
│   └── review/                   #    ReviewItem, Decision
│
└── shared/                       # 6. Нижний слой — без бизнес-смысла
    ├── api/                      #    BASE, V1, _formData, Telemetry, ExtractOptions
    └── config/                   #    REVIEW_THRESHOLD, прочие константы
```

Правила слоёв FSD (соблюдаются конвенциями + path-aliases)

* Слой может импортировать только из **нижних** слоёв (`app → pages → widgets → features → entities → shared`).
* Слайсы одного слоя **никогда** не импортируют друг друга напрямую. Только через `entities`/`shared`.
* Каждый слайс отдаёт публичную поверхность через `index.ts` (barrel). Внешние импорты идут через barrel, не во внутренние файлы.
* Path-alias `@/*` → `frontend/src/*` прописан и в `tsconfig.app.json`, и в `vite.config.ts`, поэтому `import { ExtractionPage } from "@/pages/extraction"` работает везде.

Сборка

* `vite build` → `dist/index-*.js` ~648 КБ (gzip 195 КБ), `index-*.css` ~27 КБ.
* 98 модулей трансформируется за ~170 мс.
* Хостится nginx'ом в контейнере `ui` на порту 80, наружу мапится 8080.

---

## 5. Вывод — насколько хорошо получилось

### Что получилось хорошо

* **Точность на сэмпле**: 10/10 reconciled, точное совпадение с эталонной таблицей по всем summary-полям и каунтам. Время, потраченное на гибридную экстракцию + repair-цикл, окупилось.
* **Генерализация действительно через промпты**: они лежат в `dobs.domain.prompts`, никаких per-bank `if`'ов нигде. Один и тот же путь обработал все 10 выписок Ixonia с двумя разными `account_last4` и переходом года в середине.
* **Demo-replay** убирает главный риск live-интервью: даун Anthropic или сюрприз по бюджету. Весь пайплайн (с live SSE, аномалиями, recurring) воспроизводится из снэпшота за ~7 секунд бесплатно.
* **Clean architecture здесь не показуха**: у каждого конкретного адаптера есть `Protocol`, композиционный корень их инъектит, тесты проверяют именно стыки (например, `tests/test_cache_redis.py` подменяет кеш-бэкенд без касания application-кода).
* **Async-throughout** означает, что один API-контейнер тянет пересекающиеся джобы без thread pools и GIL-contention'а; worker-контейнер масштабируется горизонтально просто `--scale worker=N`.
* **FSD на фронте** делает React-сторону читабельной: у каждого концепта своя папка, страница композирует виджеты, направление импорта невозможно перепутать.
* **121 тест за 11 секунд** — достаточно быстро, чтобы гонять на каждое сохранение во время рефакторинга.
* **17 endpoint'ов, 4 tier'а, 2 backend'а, 1 контракт**: публичная сигнатура `extract()` не ломалась ни разу — ни при async-рефакторе, ни при clean-arch порте, ни при добавлении очереди.

### Честные слабые места

* **Нет стриминга OCR**: весь PDF загружается в память и OCR'ится разом. Для bundled 53 МБ сэмпла нормально, для ≥200 МБ выписок потребуется чанкование.
* **Local-LLM tier (Ollama qwen2.5)** работает, но медленнее и менее точен, чем cloud-tier'ы. Подходит как fallback или для чувствительных данных, но demo по умолчанию идёт через `balanced` (Sonnet).
* **Genералиzация на действительно неизвестных layouts на момент интервью не проверена** — уверенность высокая, потому что промпты layout-agnostic, а в тестовом сэмпле есть внутреннее разнообразие, но единственный способ убедиться — запустить во время демо на выписке Wells Fargo / Chase / BoA.
* **Бандл фронта 648 КБ без сплита** (основная масса — react-pdf). Code-split на PDF-превью срезал бы initial bundle процентов на 40; отложил, потому что demo гоняется локально.
* **Один pytest-кейс пропущен** (`test_sse_replay_completes_with_done_event`): teardown loop'а TestClient'а гоняется с `call_soon_threadsafe` в worker-треде. Эквивалентный live-путь проверяется через `test_extract_replay_returns_full_payload` плюс Docker smoke.
* **У воркеров нет autoscaler'а**: `docker compose up --scale worker=4` работает, но Kubernetes / HPA нет. Вне рамок 3–6 часов интервью.

### Итог

ТЗ просило функцию, которая сходится. На выходе — multi-tier extraction-сервис
с clean-architecture ядром, async-очередью, live UI, audit-логом, детекцией
аномалий и zero-cost demo-режимом, построенный на дисциплине, которая
переживает и интервью, и реальный production-rollout.

Репозиторий — это deliverable; демо запускается одним `docker compose up`.
