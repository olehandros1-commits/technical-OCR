# CLAUDE.md — guidance specific to Claude Code agents

This complements [AGENTS.md](./AGENTS.md). Read that first.

## Claude-Code-specific tips

### Slash skills

- `/oh-my-claudecode:ralph` for long-running fix-and-verify loops on this codebase
- `/oh-my-claudecode:ultrawork` for parallel work across independent files
- `/oh-my-claudecode:team` if you want to dispatch multiple specialist agents (architect + executor + critic)
- `/oh-my-claudecode:ai-slop-cleaner` after Cursor / Copilot have made a mess

### Memory hints worth saving

Already saved at `~/.claude/projects/c--Users-Admin-WebstormProjects-dobs/memory/`:
- User profile (dobs.ai interview prep, budget-sensitive, demo-first)
- Architecture map of `src/dobs/`
- Working style preferences (terse responses, no emojis, no comments unless intent is non-obvious)

### When the user says "go" / "давай" / "сделай"

- Default to **execution, not planning** — the user has already validated the plan via earlier turns
- Use parallel `Agent` calls for independent file groups (frontend / mypy / docs are all parallel-safe)
- Pre-commit / ruff / mypy: **run them automatically**, don't ask permission
- Docker rebuilds: ask if it'll take > 30s and there's an alternative

### Verification recipe (must pass before claiming done)

1. `EXTRACTOR_DEMO_REPLAY=1 uv run pytest tests/ -q --tb=line` → 154 passed, 1 skipped
2. `uv run ruff check src/ tests/` → 0 errors
3. `uv run ruff format --check src/ tests/` → all formatted
4. `uv run mypy src/dobs/` → 0 errors (or documented `# type: ignore[code]` with one-line reason)
5. Smoke: `curl -X POST localhost:8000/api/v1/extraction/extract -F "pdf=@Binder2_Redacted.pdf" -F "tier=balanced"` → 10/10 reconciled, ~7s

### Anti-patterns to flag when reviewing my changes

- Module-level `_helper()` in `domain/services/` or `application/services/` — convert to private method on class
- `dict` / `list` return type in public API — request TypedDict / Pydantic
- New port without entry in `tests/test_di_container.py._PORTS` — won't be exercised by wiring test
- `except Exception: pass` — must become `log.warning(...)` + named SSE event
- `asyncio.create_task(...)` outside `BackgroundJobRunner` — will orphan on shutdown
- Mutating a Dishka-provided dep (e.g. `handler._event_bus = …`) — use `bind_event_bus()` context

### When stuck

- Run `uv run mypy src/dobs/ 2>&1 | head -30` first — many seeming-bugs are typing issues
- Check `tests/test_di_container.py` resolves the port you're working with — if not, Dishka isn't wired
- For SSE issues, `docker compose -f docker/docker-compose.yml logs api worker | grep -i event` shows the event chain

## What the user values

1. **No comments** unless the WHY is non-obvious (rename rather than comment).
2. **Terse text output** — no preamble, no recap, no "let me explain". Direct answers.
3. **Honest assessments** — if the change is risky or incomplete, say so. They explicitly asked for "REVISE not ACCEPT" verdicts in the past.
4. **Cost awareness** — never trigger real Anthropic calls without explicit ask. `EXTRACTOR_DEMO_REPLAY=1` is the default.
5. **Production-discipline** — they've gone through 6 rounds of hardening. Don't regress to "MVP-style" patterns.
