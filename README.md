# dobs.ai — Bank Statement Extraction Agent

A production-grade extraction pipeline that turns scanned/OCR'd bank-statement
PDFs into reconciled, structured JSON. Built for the dobs.ai technical interview
(Option 4) and extended into a full clean-architecture solution with an async
backend, FSD frontend, background workers, audit log, anomaly detection,
recurring-transaction analytics, and a zero-cost demo-replay mode.

[Русская версия](./README_RU.md)

---

## 1. How to run · architecture overview

### One-command Docker demo (zero cost)

```bash
git clone git@github.com:olehandros1-commits/technical-OCR.git dobs
cd dobs

# Optional — only needed for real LLM calls. Demo mode does not need it.
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Bring up api + worker + redis + ui in replay mode (~7 s for 10 statements).
EXTRACTOR_DEMO_REPLAY=1 docker compose -f docker/docker-compose.yml up -d

# UI:           http://localhost:8080
# REST API:     http://localhost:8000
# OpenAPI docs: http://localhost:8000/docs
```

Drop `Binder2_Redacted.pdf` from the repo root into the UI, hit **Extract**, watch
the SSE pipeline stream and the 10 reconciled statements render with anomalies,
recurring groups, and a clickable PDF preview.

### Without Docker (local Python)

```bash
pip install -e ".[dev,redis,queue,streamlit]"
EXTRACTOR_DEMO_REPLAY=1 dobs Binder2_Redacted.pdf --out results.json
pytest    # 121 passed, 1 skipped
```

### Live (real cloud) run

```bash
unset EXTRACTOR_DEMO_REPLAY        # spend gate
docker compose -f docker/docker-compose.yml up -d
# Then in the UI pick a tier: premium / balanced / cheap / local
```

### High-level architecture

```
┌─────────────┐    SSE     ┌──────────────┐    arq/Redis    ┌──────────────┐
│   React +   │ ─────────▶ │   FastAPI    │ ─────────────▶ │   Worker(s)  │
│   FSD UI    │            │ (presentation)│                │ (composition │
│             │ ◀───── HTTP│              │                │  root + DI)  │
└─────────────┘            └──────┬───────┘                └──────┬───────┘
                                  │                                │
                                  ▼                                ▼
                     ┌──────────────────────────────────────────────────┐
                     │              Clean-Architecture Core             │
                     │  presentation → application → domain ← infra     │
                     │   • Ports (Protocols) on the inside              │
                     │   • Adapters (Anthropic, Ollama, SQLite, Redis,  │
                     │     Tesseract, Vision-LLM, Clearbit) on outside  │
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

Single PDF arrives → uploaded via `/api/v1/extraction/jobs` → enqueued to arq
→ worker container picks it up → runs OCR (skip / tesseract / vision-LLM) →
LLM-segments the PDF into individual statements → each statement extracted in
parallel through summary → transactions → reconciliation → repair (if needed)
→ optional enrich → anomaly + recurring + forensic + continuity audits →
results streamed back over Redis pub/sub → SSE to the browser → final
`done` event triggers `GET /jobs/{id}` to fetch the full payload.

---

## 2. Requirements (ТЗ) coverage · extras built on top

### Mandatory (from the spec)

| Requirement | Where it lives | Status |
|---|---|---|
| `extract(pdf_path, txt_path=None) -> dict` | `dobs.application.commands.extraction.extract_statement` (+ CLI wrapper `dobs.presentation.cli.extract`) | ✅ Stable, async-first, with sync CLI bridge |
| Schema: `account`, `summary`, `transactions[]` | `dobs.domain.entities.statement.Statement` + value objects | ✅ Mirrored by frontend `entities/statement/model/types.ts` |
| No hallucinated numbers | `dobs.domain.services.reconcile` + `repair_statement` loop | ✅ Reconciliation gate before output |
| Must reconcile (begin + dep − wdr = end) | `dobs.domain.services.reconcile` | ✅ Verified on bundled sample: **10/10 reconciled** |
| Generalize to new banks via prompts | `dobs.domain.prompts` (no per-bank code) | ✅ Same prompts handle all 10 Ixonia layouts; designed for unseen banks |
| Way to run: CLI / HTTP / UI | `dobs` CLI, FastAPI `/api/v1/*`, React UI, Streamlit UI | ✅ All four shipped |

**Self-reported accuracy on the bundled sample (`Binder2_Redacted.pdf`)**

* 10/10 statements reconciled (`begin + dep − wdr = end`, within 1 cent tolerance)
* Account `last4`, period, deposits/withdrawals counts/totals: exact match to the etalon table
* 102 anomalies surfaced for review, 2 recurring vendor groups detected

### Extras built on top of the spec

Engineering quality

* **Async-throughout**: every I/O call is `async`. AsyncAnthropic + `ollama.AsyncClient` + `aiosqlite` + `httpx.AsyncClient` + `arq`. No `time.sleep`, no blocking SQLite, no `threading.Thread` in the hot path.
* **Clean architecture / hexagonal**: `presentation → application → domain ← infrastructure`. Ports defined as `typing.Protocol`s in `application/ports/`, adapters in `infrastructure/adapters/`.
* **SOLID, enforced**: SRP per Command/Query/Handler; OCP via ports; LSP for backend substitution; ISP (10 small ports, not 1 god-port); DIP (handlers depend on Protocols).
* **CQRS-lite**: Commands write, Queries read, each handler in its own file.
* **Dependency injection via the composition root**: `dobs.main.composition_root.Container` constructor-injects every port. No service-locator, no globals.
* **Multi-tenant**: per-request `contextvars.ContextVar` for tenant scope; cache keys, audit records, and reviews are tenant-namespaced.
* **121 tests** (115 unit + 6 job-queue), `asyncio_mode="auto"`, run in 11 s.

Functional features (beyond the spec)

* **4 quality/cost tiers**: `premium` (Opus repair), `balanced` (Sonnet), `cheap` (Haiku), `local` (Ollama qwen2.5). Each tier picks its own model trio + OCR mode + enrichment defaults.
* **Two LLM backends**: Anthropic (cloud) and Ollama (host-local via `host.docker.internal`).
* **Hybrid extraction**: deterministic table parser first, then LLM repair for rows the parser couldn't shape. Saves both cost and latency.
* **Repair loop**: if reconciliation fails, the failure delta is fed back to a `REPAIR_SYSTEM` prompt with the previous output for targeted correction.
* **Anomaly detection** (6 kinds, 3 severities): duplicate pairs, date-out-of-period, running-balance drift, round-number outliers, size outliers, low-confidence.
* **Recurring-transaction detection**: vendor-keyed cadence analysis (weekly / fortnightly / monthly / quarterly / irregular) with next-payment prediction.
* **Forensic anomaly detection**: statistical heuristics (Benford-ish round-number bias, repeated identical amounts).
* **Continuity audit**: cross-statement balance chain check on the same `account_last4`.
* **Vendor enrichment**: seed lookup + Clearbit logo fetch, composite with caching.
* **HITL review queue**: low-confidence + warn/error anomalies surface to the UI; reviewer decisions persisted to `reviews.db` with full audit trail.
* **Lessons store**: failed extractions logged with their repair pattern; future similar failures can be primed.
* **Server-Sent Events**: live pipeline progress (`ingest_start` → `segment_done_all` → per-segment `summary_done` / `transactions_done` / `reconcile` / `segment_done` → `done`).
* **Background job queue**: arq + Redis with one or more worker containers. `/jobs` enqueues, workers process, events flow back over Redis pub/sub.
* **Demo replay mode** (`EXTRACTOR_DEMO_REPLAY=1`): zero-cost playback of a recorded extraction snapshot for live demos and CI smoke. Streams realistic events with delays.
* **Excel export**: multi-sheet workbook with live SUMIF formulas, conditional formatting, continuity sheet.
* **PDF annotation overlay**: click any transaction row in the UI, the PDF preview scrolls to the right page and highlights the matching text span (fuzzy-search through `pdfjs` text layer).
* **Audit log**: every extraction recorded in `audit.db` with tier, backend, source SHA-256, statement count, reconciled count, cost, elapsed time, operator, client IP, prompts hash.
* **API-key middleware**: optional `EXTRACTOR_API_KEYS` env enables per-request auth.
* **Spend cap**: hard ceiling per process to prevent runaway API spend.
* **Telemetry collection**: tokens in/out, cache reads/writes, elapsed seconds, cost — surfaced in the UI strip and the `/api/v1/telemetry` endpoint.
* **`diff` endpoint**: structurally compare two extractions for regression-testing prompt changes.
* **`explain` endpoint**: ask the LLM to explain a single anomaly in plain text.
* **17 REST endpoints** under `/api/v1/*` — extraction, jobs, audit, cache, telemetry, tiers, reviews, explain, diff, export, health.
* **Streamlit UI** as an alternative thin client (in addition to the React app).

---

## 3. Backend code architecture

Pattern: **Clean Architecture / Hexagonal with CQRS-lite, fully async, SOLID-enforced.**

```
src/dobs/
├── domain/                       # Pure: no I/O, no frameworks, no async-required
│   ├── entities/                 # Identity-bearing objects: Statement, AuditRecord
│   ├── value_objects/            # Frozen+slots: Account, Period, Summary, Transaction
│   ├── services/                 # Domain logic: reconcile, anomaly_detector,
│   │                             # continuity_auditor, forensic_detector, recurring_detector,
│   │                             # prompt_sanitizer
│   ├── errors/                   # Domain-level exceptions
│   ├── prompts.py                # SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM
│   └── specifications/           # Specification[T] pattern for predicates
│
├── application/                  # Orchestrates domain. All async.
│   ├── ports/                    # Protocol contracts (10):
│   │                             # LLMBackendPort, OcrEnginePort, StatementCachePort,
│   │                             # AuditSinkPort, ReviewStorePort, EventBusPort,
│   │                             # VendorLookupPort, TelemetryCollectorPort,
│   │                             # LessonsStorePort, JobQueuePort, JobStorePort
│   ├── commands/                 # Writes (CQRS-C):
│   │   ├── extraction/           # ExtractStatement, ExtractSummary, ExtractTransactions,
│   │   │                         # ExtractTransactionsHybrid, PrevalidateDocument,
│   │   │                         # RepairStatement, EnrichTransactions
│   │   ├── cache/                # BustCache, ClearCache
│   │   └── review/               # RecordReview
│   ├── queries/                  # Reads (CQRS-Q):
│   │                             # DiffExtractions, EstimateCost, ExplainAnomaly,
│   │                             # GetAuditLog, GetCacheKeys, GetReviews,
│   │                             # GetTelemetry, GetTiers
│   └── services/                 # Cross-handler helpers:
│                                 # segmenter, chunking, spend_guard, cost_estimate,
│                                 # lessons_helpers
│
├── infrastructure/               # Concrete adapters. The only place with side effects.
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
│       ├── tenant/               # ContextTenantBinder (contextvars-based)
│       ├── replay/               # DemoReplayPlayer (zero-cost demo mode)
│       └── jobs/                 # MemoryJobStore, RedisJobStore, ArqJobQueue,
│                                 # AsyncioJobQueue
│
├── presentation/                 # Adapters for delivery mechanisms
│   ├── api/http/
│   │   ├── app_factory.py        # create_app() — dependency_overrides wired here
│   │   ├── middleware/           # api_key, tenant, request_id, cors
│   │   └── v1/                   # Router-per-domain: extraction, telemetry, audit,
│   │                             # cache, reviews, diff, health
│   ├── cli/extract.py            # Click CLI → asyncio.run(_run(...))
│   ├── streamlit/app.py          # Thin HTTP client to /api/v1/*
│   └── export/excel.py           # openpyxl workbook with live formulas
│
└── main/                         # Composition root
    ├── composition_root.py       # Container — lazy singletons, constructor DI,
    │                             # _ReplayingExtractHandler wrapper,
    │                             # adapter wrappers for protocol-method-name mismatches
    ├── config/settings.py        # AppSettings (env-driven, no kwargs)
    └── worker.py                 # arq WorkerSettings: dobs.main.worker
```

Key conventions

* **Constructor signature**: `def __init__(self, /, *, dep: Port) -> None`. Positional-only `self` + keyword-only deps prevent accidental positional binding.
* **Dataclasses**: `frozen=True, kw_only=True, slots=True` for value objects and commands. `eq=False, kw_only=True` for entities (identity-bearing, need `oid: str`).
* **Lazy container**: every port is built once on first access, cached on the container. Singletons by lifetime, not by static state.
* **No service locator**: the API's `app_factory.create_app()` wires `dependency_overrides` for FastAPI routers; the CLI builds its own container; the worker builds its own. No global container.
* **Replay handler**: `_ReplayingExtractHandler` wraps the real handler. If `EXTRACTOR_DEMO_REPLAY=1`, it routes to `DemoReplayPlayer.replay()` which forwards events through the same `event_bus`, so SSE clients can't tell the difference.
* **Demo replay is wired at the composition root**, not in the router. That means the same zero-cost path works for the synchronous `/extract`, the async `/jobs` flow, the CLI, and the Streamlit UI.

---

## 4. Frontend code architecture

Pattern: **Feature-Sliced Design (FSD), strict layers, `@/`-aliased imports.**

```
frontend/src/
├── app/                          # 1. Top layer — composition root
│   ├── main.tsx                  #    React 18 createRoot + StrictMode
│   ├── App.tsx                   #    Thin shell: <ExtractionPage />
│   ├── App.css, index.css        #    Global styles
│   └── index.ts
│
├── pages/                        # 2. Routes — own page-level state
│   └── extraction/
│       ├── ui/ExtractionPage.tsx #    Owns top-level state, wires widgets + features
│       └── index.ts
│
├── widgets/                      # 3. Composite UI blocks
│   ├── statement-card/           #    Per-statement summary + transactions + anomalies
│   ├── pipeline-events/          #    LiveProgress (SSE feed) + TelemetryStrip
│   ├── review-queue/             #    HITL queue
│   ├── time-series-dashboard/    #    Cross-statement charts
│   ├── diff-view/                #    Side-by-side extraction diff
│   └── pdf-preview/              #    react-pdf with click-to-highlight
│
├── features/                     # 4. User-driven actions, own their API client
│   ├── extract-job/              #    createJob + streamJobEvents + getJobResult
│   ├── upload-file/              #    FileDropzone
│   ├── tier-select/              #    Toolbar with tier/backend/OCR/enrich/parallel
│   ├── download-xlsx/
│   ├── explain-anomaly/
│   ├── diff-extractions/
│   └── review-decision/
│
├── entities/                     # 5. Domain types + UI tightly coupled to one entity
│   ├── statement/                #    Account, Period, Summary, StatementResult
│   ├── transaction/              #    + TransactionsTable.tsx
│   ├── anomaly/                  #    Anomaly, severities, kinds
│   ├── reconciliation/           #    + ReconciliationChart.tsx
│   ├── recurring-group/          #    + RecurringPanel.tsx
│   ├── tier/                     #    + listTiers() API
│   ├── pipeline-event/
│   └── review/                   #    ReviewItem, Decision
│
└── shared/                       # 6. Bottom layer — no business semantics
    ├── api/                      #    BASE, V1, _formData, Telemetry, ExtractOptions
    └── config/                   #    REVIEW_THRESHOLD, other constants
```

FSD layer rules (enforced by convention + path aliases)

* A layer may import only from layers **below** it (`app → pages → widgets → features → entities → shared`).
* Slices on the same layer **never** import each other directly. They go through `entities`/`shared`.
* Every slice exposes its public surface via `index.ts` (barrel). External imports use the slice barrel, never internal files.
* Path alias `@/*` → `frontend/src/*` is wired in both `tsconfig.app.json` and `vite.config.ts`, so `import { ExtractionPage } from "@/pages/extraction"` works everywhere.

Build output

* `vite build` → `dist/index-*.js` ~648 KB (gzip 195 KB), `index-*.css` ~27 KB.
* 98 modules transformed in ~170 ms.
* Served by nginx in the `ui` container on port 80, exposed on host port 8080.

---

## 5. Conclusion — how well it turned out

### What works well

* **Correctness on the spec sample**: 10/10 reconciled, exact match against the etalon table for all summary fields and counts. Spending the time on a hybrid extractor + repair loop paid off.
* **Generalization is genuinely prompt-driven**: prompts live in `dobs.domain.prompts`, no per-bank `if` branches anywhere. The same code path handled all 10 Ixonia statements with two different `account_last4` values and a mid-year period rollover.
* **Demo-replay mode** removes the largest risk of a live interview: an Anthropic outage or budget surprise. The whole pipeline (with live SSE events, anomaly counts, recurring detection) replays from a snapshot in ~7 seconds at zero cost.
* **Clean architecture is not theatre here**: every concrete adapter has a `Protocol` it implements, the composition root injects them, and tests exercise the seams (e.g. `tests/test_cache_redis.py` swaps the cache backend without touching application code).
* **Async-throughout** means a single API container processes overlapping jobs without thread pools or GIL contention; the worker container scales horizontally just by raising the replica count.
* **FSD on the frontend** makes the React side legible: every domain concept has its own folder, the page composes widgets, and the import direction is impossible to confuse.
* **121 tests in 11 seconds** — fast enough to run on every save during refactors.
* **17 endpoints, 4 tiers, 2 backends, 1 contract**: the public `extract()` signature has never broken, even across the async refactor + clean-arch port + queue addition.

### Honest weaknesses

* **No streaming OCR**: the whole PDF is loaded into memory and OCR'd in one go. Fine for the bundled 53 MB sample, would need chunking for ≥200 MB statements.
* **Local-LLM tier (Ollama qwen2.5)** is functional but slower and lower-accuracy than the cloud tiers. Acceptable as a fallback or for sensitive data, but the demo always defaults to `balanced` (Sonnet).
* **Generalization to *truly* unseen layouts is unverified at interview time** — confidence is high because the prompts are layout-agnostic and the test sample has internal variation, but the only way to be sure is to throw a Wells Fargo / Chase / BoA statement at it during the demo.
* **Frontend bundle is 648 KB un-split** (react-pdf is the bulk). A code-split on the PDF preview would cut the initial bundle by ~40%; deferred because the interview demo runs locally.
* **One pytest case is skipped** (`test_sse_replay_completes_with_done_event`): TestClient's loop teardown races with the worker thread's `call_soon_threadsafe`. The equivalent live path is verified via `test_extract_replay_returns_full_payload` plus the Docker smoke run.
* **Worker scaling has no autoscaler**: `docker compose up --scale worker=4` works but there's no Kubernetes / HPA setup. Out of scope for a 3–6 hour interview brief.

### Verdict

The spec asked for a function that reconciles. What shipped is a multi-tier
extraction service with a clean-architecture core, async queue, live UI, audit
log, anomaly detection, and a zero-cost demo path — built on top of a discipline
that survives both interview scrutiny and a real production rollout.

The repo is the deliverable; the demo is one `docker compose up` away.
