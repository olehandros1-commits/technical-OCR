# Bank Statement Extraction Agent (русская версия)

> Production-grade агент для извлечения структурированных данных из
> банковских выписок: **гибрид детерминистики и LLM**, **двойной
> backend** (Anthropic Claude в облаке **или** локальный Ollama
> qwen2.5), защита от prompt-injection, reconciliation как
> first-class output, adaptive repair, категоризация и forensic
> anti-fraud, **time-series аналитика**, HITL-очередь ревью,
> мультиформатный ingest (PDF / image / xlsx / html), **Excel
> экспорт с живыми SUMIF формулами**, React + TypeScript UI с
> live-стримом, развёртывание одной командой через Docker Compose.
>
> **На bundled Ixonia sample: 10/10 statements reconciled, каждое
> поле summary совпадает с эталоном bit-exact, 1 671 транзакция
> извлечена. 119/119 тестов pass. Полный document re-run на тёплом
> кэше: 1.2 секунды. Cold-cache balanced-tier: ~$1.7-3.2 на 10
> statements.**

Сделано в рамках технического собеседования dobs.ai (Option 4).

---

## TL;DR

```bash
# 1. Backend
pip install -e .
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 2. CLI (cloud)
extract-statement Binder2_Redacted.pdf --txt ixonia_ocr.txt \
    --enrich --out out/ixonia.json --xlsx out/ixonia.xlsx

# 3. CLI (локальная Ollama, после `ollama pull qwen2.5:14b`)
extract-statement Binder2_Redacted.pdf --txt ixonia_ocr.txt --tier local

# 4. Function call (точная сигнатура из ТЗ)
python -c "from extractor import extract; import json; \
  print(json.dumps(extract('Binder2_Redacted.pdf', 'ixonia_ocr.txt'), indent=2))"

# 5. Полный стек (FastAPI + React + Ollama optional) одной командой
docker compose up --build
#   -> http://localhost:8080   React UI с live SSE стримом
#   -> http://localhost:8000   FastAPI + OpenAPI на /docs

# 6. Demo-режим без затрат на API
EXTRACTOR_DEMO_REPLAY=1 docker compose up --build
#   -> любой extract отыгрывает сохранённый snapshot за ~7 сек, $0
```

---

## Соответствие ТЗ

### Что просили (из «Option 4: Bank Statement Extraction Agent»)

| Требование ТЗ | Где реализовано | Статус |
|---|---|---|
| Функция `extract(pdf_path, txt_path=None) -> dict` | [`pipeline.extract()`](src/extractor/pipeline.py) | ✅ Сигнатура точно по ТЗ |
| Выход: `{account, summary, transactions}` с указанными полями | [`schemas.Statement.to_grading_dict()`](src/extractor/schemas.py) | ✅ Bit-exact |
| Способ запуска: CLI / HTTP endpoint / one-field UI | CLI + FastAPI + React UI + Streamlit UI + gRPC | ✅ Все 4 |
| Значения только из документа, без галлюцинаций | Правила в [`prompts.py`](src/extractor/prompts.py) + reconciliation + Pydantic `extra="forbid"` | ✅ |
| Reconciliation: `beginning + deposits - withdrawals = ending`, явное флагирование mismatch | [`reconcile.py`](src/extractor/reconcile.py) + [`_reconciliation`](src/extractor/schemas.py#ReconciliationResult) поле в каждом результате | ✅ |
| Generalization на новые банки — через промпты/архитектуру, не code edits | Промпты описывают **категории секций** (Checks Paid → withdrawal, Daily Balance Summary → ignore), не Ixonia-specific метки. LLM-segmentation fallback для неизвестных layout. | ✅ |
| README с архитектурой + self-reported accuracy + known weaknesses | [README.md](README.md) (EN) + [README_RU.md](README_RU.md) (RU) + [ARCHITECTURE.md](ARCHITECTURE.md) | ✅ |
| 30-минутное демо | [Demo plan](README.md#demo-30-min) в README + DEMO_REPLAY режим для нулевых затрат | ✅ |

### Эталонные результаты ТЗ — 10/10 совпадение

| # | Период | Account | Dep# | Dep$ | With# | Reconciled |
|---|---|---|---|---|---|---|
| 1 | Apr 2025 | 4664 | 81 | $1,214,254.05 | 111 | ✅ OK |
| 2 | May 2025 | 4664 | 95 | $926,416.11 | 142 | ✅ OK |
| 3 | Jun 2024 | 4664 | 63 | $1,050,851.95 | 99 | ✅ OK |
| 4 | Jul 2024 | 4664 | 84 | $848,578.92 | 82 | ✅ OK |
| 5 | Aug 2024 | 4664 | 83 | $1,178,227.39 | 88 | ✅ OK |
| 6 | Sep 2024 | 4664 | 71 | $1,085,703.81 | 118 | ✅ OK |
| 7 | Sep 2024 | 4623 | 13 | $336,565.07 | 35 | ✅ OK |
| 8 | Oct 2024 | 4664 | 83 | $1,187,061.65 | 96 | ✅ OK |
| 9 | Nov 2024 | 4664 | 75 | $847,969.53 | 120 | ✅ OK |
| 10 | Dec 2024 | 4664 | 67 | $1,223,865.12 | 65 | ✅ OK |

Регрессия залочена тестом
[`tests/test_regression_golden.py`](tests/test_regression_golden.py).

### Что сделали сверх ТЗ (различимые на демо за 5 минут)

1. **Adaptive repair loop** — точные дельты, никаких retry-N-times,
   останавливается при diminishing returns.
2. **8 стадий → 10 стадий**: добавили forensic anti-fraud
   (Benford / vendor concentration / velocity / weekend / round
   numbers) и cross-statement continuity audit (ending = next
   beginning).
3. **Excel экспорт с живыми SUMIF/COUNTIF/IF** — 6 листов, не
   value-only dump.
4. **Двойной LLM backend** (cloud Claude + local Ollama qwen2.5)
   за одним интерфейсом `LLMBackend`. Tier-профили premium /
   balanced / cheap / local переключают всю цепочку моделей одним
   флагом.
5. **Multi-format ingest**: PDF / image (PNG/JPG телефон-фото) /
   xlsx / html / encrypted PDF detection / corrupt detection.
6. **Защита от prompt-injection** в 4 слоя: sandwich pattern,
   pattern stripping, Pydantic output validation, PII redaction.
7. **HITL review queue** с persistent SQLite reviews (append-only
   audit trail) + LLM "explain anomaly" кнопка.
8. **RLAIF-lite**: после успешного repair записывается lesson,
   которая инжектится как few-shot hint в следующие extracts.
9. **Time-series dashboard** в UI: net cash flow per period, top
   vendors, by-category breakdown, biggest transactions — отвечает
   на немой вопрос "ОК извлекли, что дальше?".
10. **Diff view** между двумя extractions того же statement (QA
    промптов).
11. **gRPC transport** параллельно REST + SSE.
12. **Spend cap** (`EXTRACTOR_SPEND_CAP_USD`) — невозможно случайно
    сжечь бюджет.
13. **Pre-validation gate** — Haiku-call за $0.001 "это вообще
    bank statement?" перед платным extractа.
14. **Audit log** — каждый extract сохранён с tier, model versions,
    prompt hash, source SHA-256, cost, latency — SOC2/SOX ready.
15. **Tenant isolation** через `X-Tenant-ID` header.
16. **PDF preview side-by-side** с extracted data в React UI.
17. **Vendor enrichment** с логотипами через Clearbit (с graceful
    no-key fallback).
18. **Recurring detection** — деттектит subscription'ы / payroll /
    rent с next-predicted-date.
19. **Demo replay** mode — отыгрывает сохранённые snapshots за $0
    для собесов / записи демо.
20. **Chunked transactions extraction** + параллельные вызовы +
    prompt caching для cloud + автоматическое переключение в
    hybrid mode для локальной модели.

---

## Архитектура (быстро)

```
PDF / TXT / Image / Excel / HTML
        |
        v
[1] Ingest           : text / Tesseract (parallel threads) / Vision-LLM / xlsx / html
                       + OCR cache by file hash
        |
        v
[2] Segment          : regex anchor "Beginning Balance as of <date>"
                       + LLM fallback для неизвестных layout
                       + skip empty pages
        |
        v
                       За каждый statement (параллельно):
        +------------+-------------+--------------+
        v            v             v              v
   [3] Summary  [4] Transactions  [5] Reconcile  [6] Repair (если fail)
   (CHEAP/Haiku)  (EXTRACT/Sonnet)  (pure code)   (REPAIR/Sonnet, delta-fed)
                  или hybrid:                          адаптивный loop,
                  regex pre-parse +                    останавливается при
                  тонкий validator                     diminishing returns
        |
        v
[7] Enrich           : категория + vendor + confidence per tx (CHEAP)
        |
        v
[8] Anomaly          : duplicate / out-of-period / size outlier / low confidence
[8b] Forensic        : Benford / vendor concentration / velocity / weekend / round numbers
        |
        v
[9] Continuity       : ending N == beginning N+1 per account
[10] Recurring       : subscription / payroll / rent grouping
        |
        v
Excel + Audit log + Cache (SQLite/Redis) + Webhook + HITL queue
```

Полная карта 25+ модулей — в [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Запуск (рецепты)

### 1. Минимум — точная функция из ТЗ

```python
from extractor import extract
result = extract("Binder2_Redacted.pdf", "ixonia_ocr.txt")
# result имеет точно ту форму что в задании
```

### 2. CLI с Excel

```bash
extract-statement Binder2_Redacted.pdf --txt ixonia_ocr.txt \
  --tier balanced --enrich \
  --out out/ixonia.json --xlsx out/ixonia.xlsx
# Stderr: live progress
# Stdout / --out: финальный JSON
# --xlsx: 6-листовая книга с живыми SUMIF формулами
```

### 3. FastAPI + React UI (Docker)

```bash
docker compose up --build
```
- React UI: http://localhost:8080
- API + Swagger: http://localhost:8000/docs

### 4. Demo-режим без затрат на API

```bash
# Подходит для собесов, demo-записей, отладки UI
EXTRACTOR_DEMO_REPLAY=1 docker compose up
```
Любой extract отыгрывает сохранённый snapshot за ~7 секунд, $0.

### 5. Локальный Ollama

```bash
ollama pull qwen2.5:14b
EXTRACTOR_BACKEND=ollama EXTRACTOR_TIER=local \
  OLLAMA_HOST=http://host.docker.internal:11434 \
  docker compose up
```
Privacy-first: ничего не покидает машину.

---

## Tier-профили (стратегия "три варианта на демо")

| Tier | Модели | Время (10 stmt) | Cost | Когда выбрать |
|---|---|---|---|---|
| **premium** | Opus repair + Sonnet extract + Haiku enrich + vision OCR | ~3 мин | $6-12 | Audit-grade extraction, regulated industries |
| **balanced** | Sonnet везде + Haiku для cheap roles | ~1.5 мин | $1.7-3.2 | **Production по умолчанию** — 10/10 на эталоне |
| **cheap** | Haiku везде | ~30-90 сек | $0.30-0.80 | Inbox triage, "это вообще банк-стейтмент?" |
| **local** | qwen2.5:14b + 7b через Ollama | ~10-30 мин | $0 | Privacy-first, offline, regulated workloads |

UI dropdown переключает Tier за один клик, при `DEMO_REPLAY=1`
любой выбор отыгрывает свой snapshot мгновенно.

---

## Self-reported accuracy на bundled sample

- **10/10 statements reconciled** до цента
- **1 671 транзакция** извлечена
- **Каждое summary поле** (bank, account_last4, period start/end,
  beginning_balance, ending_balance, deposits_total, deposits_count,
  withdrawals_total, withdrawals_count) — bit-exact match
- **Cost для cloud (balanced)**: ~$1.7-3.2 на cold-cache run,
  ~$0 на тёплом кэше
- **119/119 unit + integration tests** проходят
- Snapshot сохранён в [`out/ixonia_extraction.json`](out/ixonia_extraction.json)
- Регрессионный тест: [`tests/test_regression_golden.py`](tests/test_regression_golden.py)

---

## Known weaknesses (честно)

| Слабость | Что есть для митигации | Production fix |
|---|---|---|
| OCR качество ограничивает потолок | Vision-LLM OCR опция (`--ocr-mode vision`), image-input поддержка | Azure Document Intelligence prebuilt-bank-statement за тем же ingest интерфейсом |
| Local LLM (14b q4) accuracy < Sonnet | Same interface, можно подменить на 70b модель | Использовать local только для enrich / categorisation, не для extraction |
| Repair имеет wall-clock budget (10 мин default) | Всегда возвращает best-seen result, флагирует non-reconciled | Очередь на manual review (HITL queue уже это умеет) |
| HITL persistence — append-only SQLite | + audit-trail на каждое решение | Заменить SQLite на tenant DB с тем же contract |
| Auth на UI | Опциональный `X-API-Key` + tight CORS | OIDC + per-tenant schemas |
| Cold first run медленный | Параллельность statements, chunked extraction, prompt caching, SQLite/Redis cache | Persistent cache в Redis (готово), pre-warm cache, batched API |

---

## Demo-план на 30 минут

См. [README.md → Demo (30 min)](README.md#demo-30-min). Если коротко:

1. **2 мин** — README, диаграмма 9 стадий, "Why this architecture" таблица
2. **5 мин** — `docker compose up`, открыть UI, drag-drop PDF + .txt, наблюдать live SSE стрим
3. **4 мин** — пройтись по результатам: Reconciliation chart, Recurring panel, Anomaly chips, Vendor chips, Time-series dashboard
4. **3 мин** — HITL queue: low-confidence транзакция → click Explain → LLM bubble с объяснением и suggested action → Approve / Reject (пишется в audit log)
5. **3 мин** — открыть Swagger на /docs, показать 15 endpoints
6. **3 мин** — переключить Tier на local, показать что архитектура pluggable. Diff view сравнить два tier-runs.
7. **4 мин** — открыть [security.py](src/extractor/security.py): drop малициозную строку в выписку, показать `[REDACTED-INJECTION]` маркер
8. **3 мин** — repair loop в действии: truncate statement, посмотреть delta feedback в SSE log
9. **3 мин** — generalization: drop в Chase / BofA выписку, показать что архитектура не меняется

---

## Файлы

```
.
|-- README.md                      # English overview
|-- README_RU.md                   # этот файл
|-- ARCHITECTURE.md                # глубокая архитектурная карта
|-- pyproject.toml                 # Python пакет + optional extras
|-- docker-compose.yml             # api + ui + (--profile local) ollama
|-- Dockerfile.api
|-- Dockerfile.frontend
|-- src/extractor/                 # 25+ модулей Python
|-- frontend/                      # React + TypeScript + Vite (15 компонентов)
|-- tests/                         # 119 тестов
|-- out/                           # cache, snapshots, audit, reviews (gitignored)
|-- examples/                      # run_ixonia.py + parity_test.py
\-- Binder2_Redacted.pdf           # bundled sample (из ТЗ)
```

---

## Лицензия

Внутренняя демо-разработка для собеседования.
