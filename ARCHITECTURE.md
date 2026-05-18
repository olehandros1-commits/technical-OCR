# Architecture

Deep-dive into how the bank statement extractor works.

## 1. Pipeline overview

```
                        ╔═══════════════════════╗
                        ║   INPUT (any format)  ║
                        ║  PDF · image · xlsx   ║
                        ║   · html · txt        ║
                        ╚═══════════╤═══════════╝
                                    │
                ┌───────────────────┼───────────────────┐
                │                   │                   │
                ▼                   ▼                   ▼
         ┌─────────────┐    ┌─────────────┐     ┌─────────────┐
         │ DEMO_REPLAY │    │ Pre-validate│     │   Ingest    │
         │  (if 1)     │    │ (cheap LLM) │     │  (Stage 1)  │
         └──────┬──────┘    └──────┬──────┘     └──────┬──────┘
                │                  ▼                   │
                │            [reject if not │          │
                │             a statement]  │          │
                │                           │          │
                │                           ▼          ▼
                │                  ┌────────────────────┐
                │                  │ Segment (Stage 2)  │
                │                  │ regex anchor +     │
                │                  │ LLM fallback       │
                │                  └─────────┬──────────┘
                │                            │
                │           ┌────────────────┼──── (parallel) ──┐
                │           ▼                ▼                  ▼
                │      ┌─────────┐     ┌─────────┐         ┌─────────┐
                │      │Statement│     │Statement│   ...   │Statement│
                │      │   N=1   │     │   N=2   │         │   N=10  │
                │      └────┬────┘     └─────────┘         └─────────┘
                │           │
                │           ▼
                │   ┌─────────────────┐
                │   │ (3) Summary     │  LLM CHEAP role
                │   └────────┬────────┘
                │            ▼
                │   ┌─────────────────┐
                │   │ (4) Transactions│  LLM EXTRACT role
                │   │  hybrid OR      │  ── for Ollama: regex pre-parse
                │   │  chunked OR     │     + tiny LLM validator
                │   │  single-call    │  ── for cloud: 4 parallel chunks
                │   └────────┬────────┘     with shared system-prompt cache
                │            ▼
                │   ┌─────────────────┐
                │   │ (5) Reconcile   │  pure Python, $0.01 tol
                │   └────────┬────────┘
                │            │ ok?
                │      ┌─────┴─────┐
                │      │ yes       │ no
                │      ▼           ▼
                │  (done)    ┌──────────────────┐
                │            │ (6) Repair LLM   │  delta-fed, adaptive
                │            │  with bigger     │  loop. Stops on no
                │            │  REPAIR-role     │  progress / diminishing
                │            │  model           │  returns / time budget.
                │            └────────┬─────────┘
                │                     │
                │                     ▼ back to (5)
                │
                │   ┌─────────────────┐
                │   │ (7) Enrich      │  category + vendor + confidence
                │   │     (optional)  │  LLM CHEAP, batched
                │   └────────┬────────┘
                │            ▼
                │   ┌─────────────────┐
                │   │ (8) Anomaly     │  pure code
                │   │     duplicate / │
                │   │     out-of-     │
                │   │     period /    │
                │   │     size / conf │
                │   └────────┬────────┘
                │            ▼
                │   ┌─────────────────┐
                │   │ (8b) Forensic   │  pure code
                │   │      Benford    │
                │   │      vendor     │
                │   │      velocity   │
                │   │      weekend    │
                │   │      round nums │
                │   └────────┬────────┘
                │            ▼
                │   ┌─────────────────┐
                │   │ (10) Recurring  │  pure code
                │   │      subscript- │
                │   │      ions / pay │
                │   └────────┬────────┘
                │            │
                ▼            ▼
         ┌────────────────────────────────┐
         │     OUTPUT AGGREGATION         │
         │  + (9) Continuity audit        │ pure code
         │  + Vendor enrichment (Clearbit)│
         │  + Audit log row               │ tier, models, prompts hash,
         │  + Cache write (if ok)         │ source SHA-256, cost
         └────────────────────────────────┘
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
       ▼                    ▼                    ▼
  ┌─────────┐         ┌──────────┐         ┌─────────┐
  │ JSON    │         │ Excel    │         │ SSE     │
  │ (spec)  │         │ (live    │         │ stream  │
  │         │         │  SUMIF)  │         │ to UI   │
  └─────────┘         └──────────┘         └─────────┘
```

## 2. Module map

| File | Purpose |
|---|---|
| **Pipeline orchestration** | |
| `pipeline.py` | Orchestrator: 10 stages, threading per statement, tier+demo_replay precedence, tenant scope, audit row, vendor post-process. Public `extract()` / `extract_all()`. |
| **Stage 1 — Ingest** | |
| `ingest.py` | Multi-format ingest (PDF / image / xlsx / html / txt). Parallel Tesseract OCR. **(file_hash, method) cache** in SQLite. Typed errors: Empty/Corrupt/Encrypted/Unsupported. |
| `ingest_vision.py` | Vision-LLM OCR via `backend.call_vision()`. Pages rendered to PNG, sent in batches. |
| **Stage 2 — Segment** | |
| `segment.py` | Regex split on `Beginning Balance as of <date>` + dedup of repeated headers + skip empty pages (≥5 candidate rows). |
| `segment_llm.py` | LLM fallback when regex finds 0 boundaries (unknown bank layout). |
| **Stage 3-4 — Extract** | |
| `extract_summary.py` | Single LLM call on segment head (~6 KB). LLMRole.CHEAP (Haiku). |
| `extract_transactions.py` | Auto-routes: hybrid for Ollama, chunked LLM for cloud (4 parallel), or single call. |
| `chunking.py` | Date-range chunking. Non-overlapping date intervals, header preservation per chunk, tail-attach for last chunk. |
| `extract_transactions_hybrid.py` | Regex pre-parse + thin LLM validator (5-10× fewer output tokens). Falls back to single-call on empty regex. |
| `parse_rows.py` | Deterministic regex parser. RawRow with date_iso (year inferred), description (amounts stripped), amounts[], balance, is_check, likely_marker. |
| **Stage 5 — Reconcile** | |
| `reconcile.py` | Pure code. Σdeposits, Σwithdrawals, counts, balance equation, $0.01 tolerance. Returns deltas. |
| **Stage 6 — Repair** | |
| `repair.py` | Adaptive loop. Best-seen result preserved. Stops on no progress / diminishing returns / wall-clock budget. Delta-fed prompt. LLMRole.REPAIR. |
| **Stage 7 — Enrich (optional)** | |
| `enrich.py` | Batched per-statement: category (14-value Literal), vendor, confidence. LLMRole.CHEAP. |
| **Stage 8 — Anomaly** | |
| `anomaly.py` | duplicate_pair, date_out_of_period, size_outlier, low_confidence, running_balance_drift. |
| `forensic.py` | Benford's law, vendor concentration > 35%, velocity bursts, weekend/holiday activity, round-number excess. |
| **Stage 9 — Continuity** | |
| `continuity.py` | Per-account chain: ending balance N == beginning N+1 within $0.01. Emits running_balance_drift anomalies. |
| **Stage 10 — Recurring** | |
| `recurring.py` | Subscription / payroll / rent grouping by (vendor, side, amount±5%). Cadence label (weekly/monthly/...). Next predicted date. |
| **Post-processing** | |
| `vendor_lookup.py` | Clearbit autocomplete + seed file + SQLite cache. Graceful no-key fallback. Logo + canonical name in response. |
| **Pluggable LLM backends** | |
| `backends/base.py` | LLMBackend interface. LLMRole: CHEAP, EXTRACT, REPAIR, VISION. ImagePart for vision. |
| `backends/anthropic_backend.py` | Tool-use + Retry-After-aware backoff + ephemeral prompt cache + spend cap hook + telemetry + tolerant string-of-JSON coercion. |
| `backends/ollama_backend.py` | format=schema constrained JSON decoding. Telemetry (cost=0). |
| **Tier profiles** | |
| `tiers.py` | PREMIUM / BALANCED / CHEAP / LOCAL dataclasses with model mappings, expected latency/cost. `apply_tier_env()` sets env-var model overrides. |
| **Persistence** | |
| `cache.py` | SQLite content-addressed StatementCache. WAL mode. delete/clear/keys for invalidation API. |
| `cache_redis.py` | RedisCache + MemoryCache + `open_cache()` resolver. Graceful Redis-down fallback to SQLite. |
| `reviews.py` | Append-only HITL decisions in SQLite. Latest-decision-wins per (statement_key, tx_index). |
| `prompt_lessons.py` | RLAIF-lite. `diagnose_repair()` extracts lesson from successful repair; `lessons_block()` injects top-N into transactions prompt. |
| `audit.py` | Append-only audit log: tier, backend, model versions, prompts_hash, source_sha256, statement counts, cost, latency, operator, client_ip. SOC2/SOX ready. |
| **Security** | |
| `security.py` | Prompt-injection defence: sandwich pattern + pattern stripping + PII redaction. 8 unit tests. |
| `security_api.py` | Optional X-API-Key middleware + tight CORS preset via env. |
| `tenant.py` | X-Tenant-ID isolation. thread-local current_tenant() + scoped_key() prefix on cache keys. |
| **Speed / cost** | |
| `chunking.py` | (see above) |
| `warmup.py` | Pre-warm Anthropic ephemeral prompt cache on first /health hit. |
| `spend_cap.py` | EXTRACTOR_SPEND_CAP_USD halts pipeline at threshold. SpendCapExceededError. |
| `cost_estimate.py` | Pre-flight USD estimate per (statements, enrich, backend, chunks). |
| `prevalidate.py` | Cheap Haiku gate: "is this a bank statement?" before paying for extract. NotABankStatementError. |
| `demo_replay.py` | EXTRACTOR_DEMO_REPLAY=1 streams saved snapshot via realistic delays. Tier-aware: `out/replays/{tier}.json`. |
| **Tracing / telemetry** | |
| `tracing.py` | OpenTelemetry spans per stage. Default no-op (test-safe). OTLP exporter via env. |
| `telemetry.py` | Thread-safe CallStats collector. Cost estimator with per-model pricing. |
| **Output formats** | |
| `export_excel.py` | 6-sheet workbook with live SUMIF/COUNTIF/IF formulas, conditional formatting, continuity audit formula, color scales on Confidence. |
| **Diff & explain** | |
| `diff_extractions.py` | Structured diff between two extractions: added/removed/changed + summary deltas. |
| `explain.py` | One-shot Haiku call: "why is this anomaly suspicious + suggested action". |
| **Interfaces** | |
| `cli.py` | extract-statement: --tier --backend --ocr-mode --enrich --xlsx --out --parallel. |
| `api.py` | FastAPI: 15 endpoints. Per-job in-process queue + SSE stream. Webhook callbacks. Tenant scope. CORS. |
| `ui_streamlit.py` | Streamlit alternative UI (multi-file, HITL, telemetry strip). |
| `grpc/*.py` | gRPC alt transport. Lazy codegen. 200 MB msg limit. |
| **Schemas** | |
| `schemas.py` | Pydantic single source of truth: Account, Period, Summary, Transaction (with category/vendor/confidence/_vendor_logo), Anomaly, ReconciliationResult, SkippedRow, Statement. |
| `prompts.py` | All system prompts. SUMMARY/TRANSACTIONS/REPAIR. Cached via Anthropic ephemeral. |

## 3. Critical contracts

### `extract(pdf_path, txt_path=None) -> dict`

Spec-mandated. Returns the FIRST statement in spec shape:
```python
{
  "account": {"bank": str, "account_last4": str | None,
              "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}},
  "summary": {"beginning_balance": float, "ending_balance": float,
              "deposits_total": float, "deposits_count": int | None,
              "withdrawals_total": float, "withdrawals_count": int | None,
              "currency": str | None},
  "transactions": [
    {"date": "YYYY-MM-DD", "description": str,
     "deposit": float | None, "withdrawal": float | None,
     "category": str | None, "vendor": str | None,
     "confidence": float | None}
  ]
}
```

For multi-statement docs use `extract_all()` which returns a list with
extra debug fields prefixed `_` (`_reconciliation`, `_anomalies`,
`_recurring`, `_skipped_rows`).

### SSE wire format

```
data: {"event": "<name>", "data": {...}, "ts": <unix>}\n\n
```

**No `event:` directive** — browsers route named events away from
`EventSource.onmessage`. Locked in by
[`tests/test_api_smoke.py::test_sse_replay_completes_with_done_event`](tests/test_api_smoke.py).

### Cache keys

Statement cache key:
`{tenant}::{period_start}_{account_last4}_{backend}_{sha256(text)[:16]}`

OCR cache key (file_hash, method) — Tesseract and vision results never
collide.

### Tier precedence

```
DEMO_REPLAY=1 > tier > backend > defaults
```

If `DEMO_REPLAY=1` is set, the pipeline NEVER calls an LLM regardless
of tier or backend (locked in by `test_extract_replay_returns_full_payload`).

## 4. Performance / cost model

| Phase | Bottleneck | Mitigation |
|---|---|---|
| OCR scanned PDF | Tesseract serial | Threaded Tesseract (DPI 120, PSM 4, OEM 1) → 17s on 99-page sample. **`(file_hash, method)` cache → 0s on repeat.** |
| Extract transactions | Output tokens | Cloud: chunked + parallel + prompt cache. Local: hybrid (regex + tiny validator) → 5-10× fewer output tokens. |
| Repair loop | LLM retries | Adaptive: stops on no progress / diminishing returns / wall-clock. |
| Total cold (10 stmt) | LLM serialisation | Statement-level parallelism (default 4 workers). |
| Warm cache | (none) | All cache hits → 1.2s total |

Cold-cache cost on `balanced` tier: ~$1.7-3.2 per 10-statement document.

## 5. Tests

| File | Tests | What it locks in |
|---|---|---|
| `test_reconcile.py` | 5 | Math correctness, $0.01 tolerance, null-count handling |
| `test_segment.py` | 2 | Boundary regex + dedup |
| `test_security.py` | 8 | Injection patterns + PII redaction |
| `test_anomaly.py` | 5 | Each anomaly rule fires |
| `test_forensic.py` | 6 | Benford / vendor / velocity / weekend / round |
| `test_continuity.py` | 4 | Chain audit + drift detection |
| `test_ingest.py` | 6 | Format detection + typed errors |
| `test_export_excel.py` | 1 | Workbook structure + SUMIF formulas |
| `test_pipeline_mocked.py` | 4 | Wire + repair-loop with mock backend |
| `test_chunking.py` | 4 | Date-range split + dedupe |
| `test_cache_redis.py` | 4 | MemoryCache + SQLite + Redis fallback resolver |
| `test_lessons.py` | 7 | RLAIF-lite diagnose + store |
| `test_tracing.py` | 2 | Span context-manager no-op safety |
| `test_tiers.py` | 8 | Catalog + env application + dispatch |
| `test_audit.py` | 3 | Record + recent ordering + prompts_hash |
| `test_spend_cap.py` | 4 | Cap, warn ratio, breach raise |
| `test_regression_golden.py` | 4 | **10/10 etalon match must never break** |
| `test_parse_rows.py` | 9 | Regex parser correctness |
| `test_hybrid_extract.py` | 3 | Regex + LLM-validator path |
| `test_recurring.py` | 7 | Subscription / payroll / rent detection |
| `test_diff_extractions.py` | 4 | Diff math correctness |
| `test_tenant.py` | 4 | Tenant isolation + scope binding |
| `test_vendor_lookup.py` | 7 | Seed + Clearbit + cache + enrich-in-place |
| `test_api_smoke.py` | 7 | **Live FastAPI end-to-end: health, tiers, extract, SSE, audit, cache, diff** |
| **Total** | **119** | |

## 6. Endpoints (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness (+ first-call warmup) |
| POST | `/extract` | Sync extract, returns JSON inline |
| POST | `/jobs` | Async extract, returns job_id |
| GET | `/jobs/{id}/events` | SSE stream of pipeline events |
| GET | `/jobs/{id}` | Final result of async job |
| POST | `/extract/bulk` | Multi-PDF or ZIP, returns per-file results |
| POST | `/export/xlsx` | Extract + return Excel workbook |
| GET | `/tiers` | Catalog of tier profiles for UI selector |
| GET | `/telemetry` | Last run's token / cost stats |
| GET | `/audit` | Recent audit log entries |
| POST | `/reviews` | Record HITL approve/reject |
| GET | `/reviews/{statement_key}` | Latest decisions for one statement |
| POST | `/explain` | LLM "why is this anomalous" + suggested action |
| POST | `/diff` | Structured diff of two extractions |
| GET | `/cache/keys` | List cached statement keys |
| DELETE | `/cache/{key}` | Bust one cached statement |
| POST | `/cache/clear` | Wipe statement cache |

OpenAPI 3 at `/openapi.json`, Swagger UI at `/docs`, ReDoc at `/redoc`.

## 7. Deployment

```bash
docker compose up --build
```

Brings up:
- `dobs-api-1` (FastAPI + Tesseract + Poppler) on :8000
- `dobs-ui-1` (nginx serving Vite build, no-cache on index.html) on :8080
- `--profile local`: also `ollama` container with persistent volume

Env vars for compose:
- `ANTHROPIC_API_KEY` (required for cloud backend)
- `EXTRACTOR_BACKEND` (anthropic/ollama, default anthropic)
- `EXTRACTOR_TIER` (premium/balanced/cheap/local)
- `EXTRACTOR_DEMO_REPLAY` (0/1, demo mode)
- `OLLAMA_HOST` (default host.docker.internal:11434)
- `EXTRACTOR_API_KEYS` (comma-separated for X-API-Key auth)
- `EXTRACTOR_SPEND_CAP_USD` (cost ceiling)
- `EXTRACTOR_CACHE_URL` (redis:// or sqlite: path)

## 8. Frontend

React 18 + TypeScript + Vite. Components in `frontend/src/components/`:

- `App.tsx` — main shell, SSE stream, state
- `Toolbar.tsx` — tier dropdown (loads from /tiers), backend, OCR mode, enrich, parallel
- `FileDropzone.tsx` — drag-drop PDF + .txt
- `LiveProgress.tsx` — SSE event log with color-coded event names
- `TelemetryStrip.tsx` — calls/tokens/cache/elapsed/cost row
- `ReviewQueue.tsx` — HITL approve/reject → POST /reviews
- `StatementCard.tsx` — per-statement: header pill, metrics, anomaly chips (with Explain button), category strip, reconciliation chart, recurring panel, transactions table, downloads
- `TransactionsTable.tsx` — filters (side / category / min confidence / search) + vendor chips
- `ReconciliationChart.tsx` — inline SVG running-balance with anomaly markers
- `RecurringPanel.tsx` — subscription / payroll / rent table
- `TimeSeriesDashboard.tsx` — cross-statement: net cash flow bars, top vendors, by-category, biggest tx
- `DiffView.tsx` — A/B select + diff metrics
- `PdfPreview.tsx` — react-pdf, sticky panel, paging, zoom

Types in `frontend/src/types.ts` mirror Pydantic schemas — schema change
on Python side surfaces as TS error on next `pnpm build`.
