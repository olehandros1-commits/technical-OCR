# AGENTS.md — playbook for AI coding agents

This file tells Claude Code / Cursor / Copilot / etc. how to work with this codebase safely and idiomatically.

## TL;DR

- **Run tests**: `EXTRACTOR_DEMO_REPLAY=1 uv run pytest tests/ -q`
- **Lint + format**: `uv run ruff check src/ tests/ --fix && uv run ruff format src/ tests/`
- **Type check**: `uv run mypy src/dobs/`
- **Boot stack**: `EXTRACTOR_DEMO_REPLAY=1 docker compose -f docker/docker-compose.yml up -d`
- **Smoke**: `curl -X POST http://localhost:8000/api/v1/extraction/extract -F "pdf=@Binder2_Redacted.pdf" -F "tier=balanced"` → 10/10 reconciled in ~7s

## Architectural rules (do not violate without strong reason)

1. **Clean architecture layers** — `src/dobs/{domain,application,infrastructure,presentation,main}/`
   - `domain/` may import from nothing in the project except other `domain/*`.
   - `application/` may import from `domain/` only.
   - `infrastructure/adapters/` may import from `application/ports/` and `domain/`.
   - `presentation/` (FastAPI routers, CLI, Streamlit) may import from `application/`, never from `infrastructure/` directly — let Dishka inject.
   - `main/di.py` wires everything together — only place that may touch any concrete class.

2. **Ports as `typing.Protocol`** — define every cross-layer contract in `application/ports/*.py` with `...` method bodies (NOT `raise NotImplementedError`).

3. **OOP-only services** — `domain/services/*` and `application/services/*` contain classes, not free functions. Helpers are private methods, not module-level `_helper()`s.

4. **Constructor injection** — every handler/adapter/service takes deps via `def __init__(self, /, *, dep: Port) -> None`. Positional-only `self`, keyword-only deps.

5. **Dataclass conventions**:
   - Value objects: `@dataclass(frozen=True, kw_only=True, slots=True)`
   - Entities (have identity): `@dataclass(eq=False, kw_only=True)` with required `oid: str`
   - Commands/Queries: `@dataclass(frozen=True, kw_only=True, slots=True)`

6. **Async-throughout** — no `time.sleep`, no blocking SQLite (`aiosqlite`), no `threading.Thread` in the hot path. Use `asyncio.to_thread` for sync I/O that can't be avoided. Use `asyncio.TaskGroup` for structured concurrency (not bare `asyncio.gather`).

7. **DI through Dishka** — handlers come from FastAPI `FromDishka[T]`, never built manually in routes. Test wiring with `tests/test_di_container.py`.

8. **No silent `except: pass`** — log via `dobs.main.logging_setup.get_logger(__name__)` and (for HTTP-path errors) emit a named SSE event.

9. **No `dict`/`list` in public signatures** — use Pydantic models or `TypedDict` so type-checker can verify boundaries.

10. **Adapter wrappers go in `infrastructure/adapters/`**, not in `main/di.py`. The DI module is for `@provide` methods only.

## Adding a new feature — workflow

| Step | What | Where |
|---|---|---|
| 1 | Define the contract | `application/ports/<name>.py` — Protocol with `...` bodies |
| 2 | Implement | `infrastructure/adapters/<area>/<name>.py` — class implementing the Protocol |
| 3 | Write the use case | `application/commands/<area>/<verb>_<noun>.py` — Command dataclass + Handler class |
| 4 | Wire | `main/di.py` — add a `@provide` returning the new Port |
| 5 | Expose | `presentation/api/http/v1/<area>/router.py` — endpoint via `FromDishka[YourHandler]` |
| 6 | Test | Unit test in `tests/test_<thing>.py` + DI smoke in `tests/test_di_container.py` (it auto-parametrises) |

## Where to put what

| Concern | Location |
|---|---|
| New DB-backed adapter | `infrastructure/adapters/<area>/sqlite_*.py` + `SqliteSessionFactory` via Dishka. **Don't open aiosqlite connections directly.** |
| New LLM provider | Subclass `StructuredOutputCaller` in `infrastructure/adapters/llm/base.py`. Implement `_invoke` + `_is_retryable`. |
| New event the pipeline emits | `await self._event_bus.publish("event_name", {"…": …})` from inside a handler. SSE clients pick it up automatically. |
| Per-request context | `dobs.main.logging_setup.request_id_ctx` (ContextVar) or `dobs.presentation.api.http.middleware.tenant.current_tenant()`. |
| Per-job event bus binding | `with bind_event_bus(StoreEventBus(store=store, job_id=…)): await handler(command)` — see `worker.py` and `router.create_job`. |

## Things you MUST NOT do

- ❌ Add `from dobs.main.di import _WhateverAdapter` — none of those exist anymore, all underscore-prefixed wrappers are deleted.
- ❌ Mutate `inner._event_bus` or any other shared singleton attribute. Use `bind_event_bus()` context manager.
- ❌ `asyncio.create_task(...)` without registering on `BackgroundJobRunner` — orphan tasks die on shutdown.
- ❌ Add comments inside functions explaining what the code does. Rename instead.
- ❌ Pass real Anthropic API key in tests / CI. Use `EXTRACTOR_DEMO_REPLAY=1`.
- ❌ Touch `out/replays/balanced.json` — it's the contract sample for `EXTRACTOR_DEMO_REPLAY` smoke.
- ❌ Run `docker compose up` from project root — the compose file is at `docker/docker-compose.yml`.

## Cost discipline

The Anthropic API key on this account has minimal budget. **All test/smoke runs must use `EXTRACTOR_DEMO_REPLAY=1`** which routes through `DemoReplayPlayer` and emits zero LLM calls. The replay still exercises:
- SSE event stream (full pipeline events)
- 10 statement parsing
- Reconciliation contract (10/10)
- Anomaly detection (102)
- Recurring detection (2)

Only set `EXTRACTOR_DEMO_REPLAY=0` for explicit user-requested live runs.

## Useful one-liners

```bash
# Quick local check (no docker)
EXTRACTOR_DEMO_REPLAY=1 uv run pytest tests/ -q --tb=line

# Pre-commit dry-run
uv run pre-commit run --all-files

# Full docker stack
EXTRACTOR_DEMO_REPLAY=1 docker compose -f docker/docker-compose.yml up -d --build

# Streamlit dev (no docker needed)
EXTRACTOR_DEMO_REPLAY=1 DOBS_API_URL=http://localhost:8000 uv run dobs-ui

# Profile a real extract
uv run py-spy record -o profile.svg -- uv run dobs Binder2_Redacted.pdf --tier balanced
```

## Project goals (current phase)

- Built for the dobs.ai technical interview (Option 4: Bank Statement Extraction Agent)
- Solo developer, no team yet
- Production-discipline because the architecture is designed to scale to one
- Budget-sensitive on Anthropic API; demo-replay is the default

If you're adding something — ask: does this preserve the 10/10 reconciliation contract on the bundled Ixonia sample? Does it work with `EXTRACTOR_DEMO_REPLAY=1`? Does it pass `mypy --strict`?
