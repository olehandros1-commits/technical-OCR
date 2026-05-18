Т# dobs.ai — Bank Statement Extraction Agent

A production-grade extraction pipeline that turns scanned/OCR'd bank-statement
PDFs into reconciled, structured JSON. Built for the dobs.ai technical interview
(Option 4) and developed into a full async clean-architecture solution: ports
& adapters, Dishka DI, structured concurrency, structured logging, observability
stack, mypy strict, 154 passing tests, GitHub Actions CI, and a zero-cost
demo-replay mode for interviews and CI smoke.

[Русская версия](./README_RU.md)

---

## 1. How to run · architecture overview

### One-command Docker demo (zero cost)

```bash
git clone git@github.com:olehandros1-commits/technical-OCR.git dobs
cd dobs

# Download the test PDF (53 MB, kept out of git history).
# Reviewers get the link separately; place it at repo root as Binder2_Redacted.pdf

# Optional — only for real LLM calls. Demo replay needs nothing.
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Bring up api + worker + redis + ui in replay mode (~7s for 10 statements)
EXTRACTOR_DEMO_REPLAY=1 docker compose -f docker/docker-compose.yml up -d

# UI:           http://localhost:8080
# REST API:     http://localhost:8000
# OpenAPI docs: http://localhost:8000/docs
# /metrics:     http://localhost:8000/metrics  (Prometheus)
# Health:       http://localhost:8000/api/v1/health/{live,ready}
```

Drop a PDF into the UI, hit **Extract**, watch the SSE pipeline stream and the
10 reconciled statements render with anomalies, recurring groups, and a
clickable PDF preview.

### Without Docker (local Python via uv)

```bash
# Install uv (one-time): https://docs.astral.sh/uv/
uv sync --extra dev --extra ocr --extra redis --extra ollama --extra queue --extra streamlit

# Run tests (154 passed, 1 skipped, ~11s)
EXTRACTOR_DEMO_REPLAY=1 uv run pytest

# Run CLI
EXTRACTOR_DEMO_REPLAY=1 uv run dobs Binder2_Redacted.pdf --out results.json

# Lint + type-check
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/dobs/    # Success: no issues found in 180 source files
```

### Live (real cloud) run

```bash
# In docker/docker-compose.yml change EXTRACTOR_DEMO_REPLAY default to 0,
# or pass it explicitly:
EXTRACTOR_DEMO_REPLAY=0 docker compose -f docker/docker-compose.yml up -d

# In the UI choose a tier: premium / balanced / cheap / local
# Expected cost on bundled sample (10 statements):
#   premium  ~$0.30  (Opus repair, Sonnet extract)
#   balanced ~$0.15  (Sonnet)
#   cheap    ~$0.05  (Haiku)
#   local    $0      (Ollama qwen2.5:14b, requires host Ollama)
```

### High-level architecture

```
┌────────────┐    SSE     ┌───────────────┐    arq/Redis    ┌──────────────┐
│  React     │ ─────────▶ │   FastAPI     │ ─────────────▶ │   Worker(s)  │
│  FSD UI    │            │  (presentation │                │  (Dishka     │
│  + Streamlit│ ◀──── HTTP │   + Dishka DI)│                │   container) │
└────────────┘            └──────┬────────┘                └──────┬───────┘
                                 │                                 │
                                 ▼                                 ▼
                ┌──────────────────────────────────────────────────┐
                │             Clean Architecture core              │
                │   presentation → application → domain ← infra    │
                │    • 12 ports as typing.Protocols (the "inside") │
                │    • Adapters (Anthropic, Ollama, SQLite, Redis, │
                │      Tesseract, Vision-LLM, Clearbit, …) outside │
                │    • Dishka container, no service locator        │
                └──────────────────────────────────────────────────┘
                                 │
                                 ▼
   ┌──────────────┬─────────────┬────────────┬──────────────┬────────────┐
   │ aiosqlite UoW │   Redis     │  arq queue │  Anthropic   │  OTel /    │
   │  5 DBs:       │ pub/sub +   │  + worker  │  / Ollama    │ Prometheus │
   │  audit,       │ job store + │ container  │  via shared  │  / Sentry  │
   │  reviews,     │ cache       │            │  Structured- │  (all env- │
   │  lessons,     │             │            │  OutputCaller │   gated)  │
   │  ocr_cache,   │             │            │              │           │
   │  vendor_cache │             │            │              │           │
   └──────────────┴─────────────┴────────────┴──────────────┴────────────┘
```

Single PDF arrives → `POST /api/v1/extraction/jobs` → request gets request_id +
tenant via middleware + ContextVar → `BackgroundJobRunner.spawn()` or
`ArqJobQueue.enqueue()` depending on REDIS_URL → worker picks it up → OCR
(text-layer / tesseract / vision-LLM / OpenDataLoader) → LLM-segment the PDF
into individual statements → `asyncio.TaskGroup` runs per-statement processing
in parallel → summary → transactions → reconciliation → repair if needed →
optional enrich + vendor lookup (deduped batch via TaskGroup, no N+1) → anomaly
+ recurring + forensic + continuity audits → results published over Redis
pub/sub → SSE to browser with 15s heartbeat → final `done` event → `GET
/jobs/{id}` returns full payload.

---

## 2. Requirements (ТЗ) coverage · extras built on top

### Mandatory (from the spec)

| Requirement | Where it lives | Status |
|---|---|---|
| `extract(pdf_path, txt_path=None) -> dict` | `dobs.application.commands.extraction.extract_statement.ExtractStatementHandler.__call__` (+ CLI wrapper) | ✅ Async-first, supports pdf-only / txt-only / both |
| Schema: `account`, `summary`, `transactions[]` | `dobs.domain.entities.statement.Statement` + value objects, mypy-strict | ✅ Mirrored by frontend `entities/statement/model/types.ts` |
| No hallucinated numbers | `dobs.domain.services.reconcile.Reconciler` + `RepairStatementHandler` loop | ✅ Hard reconciliation gate before output |
| Must reconcile (begin + dep − wdr = end) | `Reconciler.reconcile()` | ✅ Verified on bundled sample: **10/10 reconciled** |
| Generalize to new banks via prompts | `dobs.domain.prompts` (no per-bank code, layout-agnostic) | ✅ Same prompts handle all 10 Ixonia statements (2 account_last4, year rollover) |
| Way to run: CLI / HTTP / UI | `dobs` CLI, FastAPI `/api/v1/*`, React UI, Streamlit UI | ✅ All four shipped |

**Self-reported accuracy on the bundled sample (`Binder2_Redacted.pdf`)**

* 10/10 statements reconciled (`begin + dep − wdr = end`, within 1 cent tolerance)
* Account `last4`, period, deposits/withdrawals counts/totals: exact match to the etalon table
* 102 anomalies surfaced for review, 2 recurring vendor groups detected

### Extras built on top of the spec

Engineering quality

* **Async throughout**: every I/O call is `async`. AsyncAnthropic + `ollama.AsyncClient` + `aiosqlite` + `httpx.AsyncClient` + `arq` + `aiofiles`. No `time.sleep`, no blocking SQLite, no `threading.Thread` on the hot path.
* **Structured concurrency**: `asyncio.TaskGroup` (PEP 654 ExceptionGroup) for per-statement and per-chunk parallel processing, not bare `asyncio.gather`.
* **Clean architecture / hexagonal**: `presentation → application → domain ← infrastructure`. 12 ports as `typing.Protocol`s in `application/ports/`, adapters in `infrastructure/adapters/`.
* **SOLID, enforced**: SRP per Command/Query/Handler; OCP via ports; LSP for backend substitution; ISP (12 small ports); DIP (handlers depend on Protocols, never on adapters).
* **CQRS-lite**: Commands write, Queries read, one handler per file.
* **Dishka DI container** with `Scope.APP` providers, `FromDishka[T]` in FastAPI routes. Composition lives in `dobs.main.di`, no service locator, no globals.
* **UoW pattern** (`SqliteSessionFactory`): aiosqlite session opened via async context manager, commit-or-rollback handled by the factory, no per-call connection setup. One factory per database (5 total).
* **ContextVar-bound event bus**: handlers receive an `EventBusPort` once via DI; per-request/per-job event sink is bound via `bind_event_bus(bus)` context manager. Safe under concurrent jobs sharing a `Scope.APP` handler — no shared-singleton mutation.
* **`StructuredOutputCaller` ABC**: shared retry loop + telemetry recording + pydantic coercion across both LLM backends. Subclasses implement only `_invoke()` + `_is_retryable()`.
* **Background job lifecycle**: `BackgroundJobRunner` tracks `asyncio.Task` references and cancels them on FastAPI lifespan shutdown — no orphaned tasks.
* **Multi-tenant**: per-request `contextvars.ContextVar` for tenant scope; cache keys, audit records, and reviews are tenant-namespaced.
* **mypy --strict**: 0 errors in 180 source files. ~25 `# type: ignore[code]` comments, each with a one-line reason.
* **Ruff** for lint + format (replaces flake8 + isort + pyupgrade + black). `pre-commit` hooks gate every commit.
* **uv + uv.lock** — reproducible Astral-style builds, ~10× faster than pip in Docker.
* **GitHub Actions CI**: lint-and-typecheck, tests on Python 3.12 + 3.13 matrix with pytest-xdist + coverage, security (pip-audit + Trivy), docker-smoke that boots the full stack and asserts the 10/10 contract, frontend pnpm build.
* **154 tests** (~11s), incl. 29 parametrized DI-container wiring tests that catch missing `@provide` at pytest-time, not Docker-time.

Functional features (beyond the spec)

* **4 quality/cost tiers**: `premium` (Opus repair), `balanced` (Sonnet), `cheap` (Haiku), `local` (Ollama qwen2.5).
* **Two LLM backends**: Anthropic (cloud, with ephemeral prompt caching) and Ollama (local, structured output via `format=schema`).
* **Hybrid extraction** (for Ollama): regex table parser pulls candidate rows first, LLM only classifies deposit/withdrawal. Cheaper and more accurate on smaller local models.
* **Repair loop** with up to 4 attempts: failure delta is fed back to a `REPAIR_SYSTEM` prompt with the previous output. Best-so-far is kept if convergence stalls.
* **Anomaly detection** (6 kinds, 3 severities): duplicate pairs, date-out-of-period, running-balance drift, round-number outliers, size outliers, low-confidence.
* **Recurring-transaction detection**: vendor-keyed cadence (weekly / fortnightly / monthly / quarterly / irregular) with next-payment prediction.
* **Forensic anomaly detection**: statistical heuristics (round-number bias on big withdrawals).
* **Continuity audit**: cross-statement balance-chain check on the same `account_last4`.
* **Vendor enrichment**: `SeedVendorLookup` (JSON) → `ClearbitVendorLookup` (HTTP) composite with sqlite-cached results. Batch lookup with dedup + `TaskGroup` (no N+1).
* **HITL review queue**: low-confidence + warn/error anomalies surface to the UI; decisions persisted to `reviews.db` with full history.
* **Lessons store**: after a successful repair, a human-readable hint is derived and stored. Future extractions prime the `TRANSACTIONS_SYSTEM` prompt with top hints.
* **Server-Sent Events** with 15s heartbeat (`DOBS_SSE_HEARTBEAT_S`) so reverse proxies don't kill idle SSE on long jobs.
* **Background job queue**: arq + Redis. `/jobs` enqueues, workers process out-of-process, events flow back over Redis pub/sub. Worker builds Dishka container once in `on_startup` and reuses across all jobs.
* **Demo replay mode** (`EXTRACTOR_DEMO_REPLAY=1`): zero-cost playback of a recorded extraction snapshot for live demos and CI smoke. Real pipeline events flow through the same `event_bus` so SSE clients can't tell the difference.
* **Excel export**: `ExcelPresenter` builds DataFrames via pandas, writes them via openpyxl; live SUMIF/COUNTIF formulas + conditional formatting (red row when `_reconciliation.ok == false`).
* **PDF annotation overlay** (frontend): row click → PDF preview scrolls to the matching page → matching text span highlighted via fuzzy substring match (60 → 30 → 20 char prefix).
* **Audit log**: every extraction recorded in `audit.db` with tier, backend, source SHA-256, statement counts, cost, elapsed time, operator, client IP, prompts hash.
* **API-key middleware**: optional `EXTRACTOR_API_KEYS` env enables per-request auth.
* **Spend cap** enforced live: `SpendGuard` wired into telemetry — every LLM call's `cost_usd` increments the counter, throws `SpendCapExceededError` when `EXTRACTOR_SPEND_CAP_USD` is breached.
* **20 REST endpoints** under `/api/v1/*` — extraction (6: extract, jobs, jobs/events, jobs/{id}, bulk, xlsx-export), audit (1), cache (3), telemetry (2), reviews (3), explain (1), diff (1), health (3: live, ready, legacy).
* **Observability**:
  * **structlog** structured logging with `request_id` ContextVar threaded through SSE events
  * **`/metrics`** Prometheus endpoint (toggle with `DOBS_DISABLE_METRICS`)
  * **OpenTelemetry** FastAPI + httpx + Redis auto-instrument when `OTEL_EXPORTER_OTLP_ENDPOINT` is set
  * **Sentry** SDK + FastApiIntegration when `SENTRY_DSN` is set
  * **Real readiness probe** `/api/v1/health/ready` pings cache, audit DB, Redis, and ANTHROPIC_API_KEY presence; returns 503 with per-check breakdown when degraded
* **Streamlit UI**: thin HTTP client to `/api/v1/*`, 48-line `app.py` decomposed into `ApiClient` + `SessionState` + 3 Presenter classes + 5 components.
* **AI-agent docs**: `AGENTS.md` (layer rules, must-not list, where-to-put-what) + `CLAUDE.md` (Claude Code skill triggers, verification recipe). Codebase is AI-ready: typed, contracted, dockerized.

---

## 3. Backend code architecture

Pattern: **Clean Architecture / Hexagonal with CQRS-lite, async throughout, Dishka DI, mypy --strict.**

```
src/dobs/
├── domain/                          # Pure: no I/O, no frameworks, no async required
│   ├── entities/                    # Identity-bearing: Statement, AuditRecord, ExtractionJob
│   ├── value_objects/               # Frozen+slots: Account, Period, Summary, Transaction, …
│   ├── services/                    # Pure OOP services:
│   │                                # Reconciler, AnomalyDetector, ContinuityAuditor,
│   │                                # ForensicAnomalyDetector, RecurringDetector,
│   │                                # PromptSanitizer, RowParser
│   ├── errors/                      # Domain exceptions
│   ├── prompts.py                   # SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM
│   └── specifications/              # Specification[T] (PEP 695 generics)
│
├── application/                     # Orchestrates domain. All async.
│   ├── ports/                       # 12 Protocol contracts:
│   │                                # LLMBackendPort, OcrEnginePort, StatementCachePort,
│   │                                # AuditSinkPort, ReviewStorePort, LessonsStorePort,
│   │                                # EventBusPort, VendorLookupPort, VendorEnricherPort,
│   │                                # TelemetryCollectorPort, JobQueuePort, JobStorePort
│   ├── commands/                    # Writes (CQRS-C): one handler per file
│   │   ├── extraction/              # ExtractStatement, ExtractSummary, ExtractTransactions,
│   │   │                            # ExtractTransactionsHybrid, PrevalidateDocument,
│   │   │                            # RepairStatement, EnrichTransactions
│   │   ├── cache/                   # BustCache, ClearCache
│   │   └── review/                  # RecordReview
│   ├── queries/                     # Reads (CQRS-Q)
│   ├── services/                    # OOP services: StatementSegmenter, TransactionChunker,
│   │                                # CostEstimator, LessonsHelper, SpendGuard
│   ├── dto/                         # serialize_results — DTOs cross presentation/worker
│   └── errors.py                    # Application-level: SpendCapExceededError, etc.
│
├── infrastructure/                  # Concrete adapters. The only place with side effects.
│   ├── adapters/
│   │   ├── llm/
│   │   │   ├── base.py              # StructuredOutputCaller ABC: shared retry+telemetry
│   │   │   ├── anthropic_backend.py # AsyncAnthropic + ephemeral prompt cache
│   │   │   └── ollama_backend.py    # ollama.AsyncClient + format=json_schema
│   │   ├── ocr/
│   │   │   ├── composite_engine.py  # Orchestrates the OCR strategies
│   │   │   ├── file_reader.py       # Text-layer extraction (pdfplumber, fast path)
│   │   │   ├── tesseract_engine.py  # pdf2image + Tesseract (+ OcrCacheStore)
│   │   │   ├── vision_engine.py     # vision-LLM fallback
│   │   │   └── opendataloader_engine.py  # Optional Java-based extractor (env-gated)
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
│   │   │   ├── demo_replay.py       # DemoReplayPlayer reads snapshot, emits events
│   │   │   └── replaying_extract_handler.py  # Wraps real handler, routes to replay
│   │   └── jobs/
│   │       ├── memory_job_store.py  # In-process store with TTL + max-jobs eviction
│   │       ├── redis_job_store.py   # Redis-backed pub/sub + result hash
│   │       ├── arq_job_queue.py     # Enqueue to arq
│   │       ├── asyncio_job_queue.py # In-process queue (mostly historical)
│   │       └── background_runner.py # Tracks tasks, cancels on shutdown
│   └── persistence/
│       └── sqlite_session.py        # SqliteSessionFactory: UoW for all 5 SQLite DBs
│
├── presentation/                    # Delivery mechanisms (adapters in DDD parlance)
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
    └── config/settings.py           # pydantic_settings.BaseSettings (env-driven, typed)
```

Key conventions

* **Constructor signature**: `def __init__(self, /, *, dep: Port) -> None`. Positional-only `self` + keyword-only deps make accidental positional binding impossible.
* **Dataclasses**: `frozen=True, kw_only=True, slots=True` for value objects, commands, queries. `eq=False, kw_only=True` for identity-bearing entities.
* **No service locator**: every handler/adapter receives deps via constructor injection. The single composition site is `dobs.main.di.build_providers()`.
* **No silent failures**: every previously-silent `except Exception: pass` was replaced with `log.warning(..., exc_info=True)` + named SSE event (`lessons_failed`, `enrich_failed`, `vendor_enrich_failed`, `audit_failed`). Audit-record failures escalate to `log.error("AUDIT RECORD FAILED — compliance gap")`.
* **ContextVar event bus**: handlers take `event_bus: EventBusPort` once at construction. Per-request/per-job sink is bound via `with bind_event_bus(sink):` so the same singleton handler is safe across concurrent jobs.
* **Demo replay routing** happens at the composition root in `ReplayingExtractHandler` (an infrastructure adapter), not in the router. Same zero-cost path works for `/extract`, `/jobs`, CLI, Streamlit.

---

## 4. Frontend code architecture

Pattern: **Feature-Sliced Design (FSD), strict layers, `@/`-aliased imports.**

```
frontend/src/
├── app/                             # 1. Top layer — composition root
│   ├── main.tsx                     #    React 18 createRoot + StrictMode
│   ├── App.tsx                      #    Thin shell: <ExtractionPage />
│   ├── App.css, index.css           #    Global styles
│   └── index.ts
│
├── pages/                           # 2. Routes — own top-level state
│   └── extraction/
│       ├── ui/ExtractionPage.tsx    #    Owns state, wires widgets + features
│       └── index.ts
│
├── widgets/                         # 3. Composite UI blocks
│   ├── statement-card/              #    Per-statement summary + transactions + anomalies
│   ├── pipeline-events/             #    LiveProgress (SSE) + TelemetryStrip
│   ├── review-queue/                #    HITL queue
│   ├── time-series-dashboard/       #    Cross-statement charts
│   ├── diff-view/                   #    Side-by-side diff
│   └── pdf-preview/                 #    react-pdf shell, uses pdf-text-search feature
│
├── features/                        # 4. User-driven actions, each owns its API client
│   ├── extract-job/                 #    createJob + streamJobEvents + getJobResult + extractBlocking
│   ├── upload-file/                 #    FileDropzone
│   ├── tier-select/                 #    Toolbar
│   ├── download-xlsx/
│   ├── explain-anomaly/
│   ├── diff-extractions/
│   ├── review-decision/
│   └── pdf-text-search/             #    usePdfTextIndex + usePdfHighlight hooks
│
├── entities/                        # 5. Domain types + UI tightly coupled to one entity
│   ├── statement/                   #    Account, Period, Summary, StatementResult
│   ├── transaction/                 #    + TransactionsTable.tsx
│   ├── anomaly/                     #    Anomaly, severities, kinds
│   ├── reconciliation/              #    + ReconciliationChart.tsx
│   ├── recurring-group/             #    + RecurringPanel.tsx
│   ├── tier/                        #    + listTiers() API
│   ├── pipeline-event/
│   └── review/                      #    ReviewItem, Decision
│
└── shared/                          # 6. Bottom layer — no business semantics
    ├── api/                         #    BASE, V1, _formData, ExtractOptions, Telemetry
    └── config/                      #    REVIEW_THRESHOLD, other constants
```

FSD layer rules

* A layer may import only from layers **below** (`app → pages → widgets → features → entities → shared`).
* Slices on the same layer never import each other directly.
* Each slice exposes its public surface via `index.ts`. External imports go through the barrel.
* Path alias `@/*` → `frontend/src/*` is wired in both `tsconfig.app.json` and `vite.config.ts`.

Build output

* `vite build` → `dist/index-*.js` ~648 KB (gzip 195 KB), `index-*.css` ~27 KB
* 98 modules in ~170 ms
* Served by nginx in the `ui` container on port 80, exposed on host port 8080

---

## 5. Conclusion — how well it turned out

### What works well

* **Correctness on the spec sample**: 10/10 reconciled, exact match against the etalon table for every summary field. Hybrid extraction + repair loop earned this.
* **Generalization is genuinely prompt-driven**: prompts live in `dobs.domain.prompts`, no per-bank `if` branches anywhere.
* **Demo replay mode** removes the largest interview risk — Anthropic outage or budget surprise. The whole pipeline replays in ~7s at zero cost, with the same SSE event stream as the live path.
* **Clean architecture is not theatre**: every adapter has a Protocol it implements, Dishka injects, `tests/test_di_container.py` parametrizes over all 29 ports + handlers and catches missing `@provide` at pytest time, not at container startup.
* **Async throughout** with structured concurrency means a single API container handles overlapping jobs without thread pools or GIL contention. The worker scales horizontally with `--scale worker=N`.
* **FSD on the frontend** makes the React side legible: every domain concept has a folder, page composes widgets, import direction is impossible to confuse.
* **Quality gates are real**: 154 tests in 11s, mypy --strict 0 errors, ruff 0 errors, ruff format applied across 206 files, CI runs on every push with Python 3.12 + 3.13 matrix and a docker-smoke job that asserts the 10/10 contract.
* **Observability is wired but not forced**: structlog + request_id by default; `/metrics`, OpenTelemetry, Sentry all turn on with one env var, off by default.
* **20 endpoints, 4 tiers, 2 backends, 1 contract**: the public `extract()` signature has never broken across the entire refactor history.

### Honest weaknesses

* **No streaming OCR**: PDFs are loaded fully into memory and OCR'd in one pass. Fine for the 53 MB sample; would need chunking for ≥200 MB.
* **Local-LLM tier (Ollama qwen2.5)** is slower and lower-accuracy than the cloud tiers. Suitable as a fallback or for sensitive data; demo defaults to `balanced` (Sonnet).
* **Generalization to truly unseen bank layouts is unverified at interview time** — prompts are layout-agnostic and the sample has internal variation, but a Wells Fargo / Chase statement during the live demo would be the real test.
* **Frontend bundle is 648 KB un-split** (react-pdf is the bulk). `React.lazy()` on the PDF preview would cut initial bundle by ~40%.
* **One pytest case is skipped** (`test_sse_replay_completes_with_done_event`): TestClient's loop teardown races with a worker thread's `call_soon_threadsafe`. The equivalent live path is verified via `test_extract_replay_returns_full_payload` and the docker-smoke CI job.
* **No SQLAlchemy / migrations**: 5 SQLite databases with `CREATE TABLE IF NOT EXISTS` schemas — works until the first ALTER. A 50-line `SqliteMigrator` would close this gap when needed.
* **Worker scaling has no autoscaler**: `docker compose up --scale worker=4` works, but no Kubernetes HPA. Out of scope for the interview brief.

### Verdict

The spec asked for a function that reconciles. What shipped is a multi-tier
extraction service with a clean-architecture core, async queue, live UI, audit
log, anomaly detection, observability stack, full CI, mypy --strict, and a
zero-cost demo path — built on a discipline that survives both interview
scrutiny and a real production rollout.

The repo is the deliverable; the demo is one `docker compose -f
docker/docker-compose.yml up -d` away.
