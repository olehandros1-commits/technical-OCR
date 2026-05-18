"""Prompt-cache warm-up.

Anthropic's ephemeral prompt cache is keyed on the verbatim system block
(plus model + max_tokens). The first call after a cold start has to write
the cache (slow); subsequent calls hit it (fast). We avoid paying that on
the user's first real request by firing one trivial call per system
prompt at startup.

For local Ollama: warm-up loads the model into VRAM and JIT-compiles the
JSON-schema decoder. Saves 10-30 s on the very first call.
"""
from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole
from extractor.prompts import SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM

log = logging.getLogger(__name__)


class _Ack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


_WARM_USER = (
    "Reply with {\"ok\": true} only. This is a cache warm-up ping; do not "
    "extract anything from this request."
)


def warm_up_backend(
    backend: LLMBackend,
    *,
    prompts: Iterable[str] = (SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM),
    parallel: bool = True,
) -> dict[str, float]:
    """Send one trivial structured call per system prompt to prime the cache.

    Returns a {prompt-tag: elapsed_seconds} dict for telemetry / logging.
    Errors are caught -- warm-up failure must never break startup.
    """
    import time
    tasks = [
        ("summary",      SUMMARY_SYSTEM),
        ("transactions", TRANSACTIONS_SYSTEM),
        ("repair",       REPAIR_SYSTEM),
    ]

    def _one(name: str, sysprompt: str) -> tuple[str, float]:
        t0 = time.time()
        try:
            backend.call_structured(
                system=sysprompt,
                user=_WARM_USER,
                response_model=_Ack,
                role=LLMRole.EXTRACT,
                max_retries=1,
            )
            elapsed = time.time() - t0
            log.info("warm-up[%s][%s] %.2fs", backend.name, name, elapsed)
            return name, elapsed
        except Exception as e:
            log.warning("warm-up[%s][%s] failed: %s", backend.name, name, e)
            return name, -1.0

    results: dict[str, float] = {}
    if parallel:
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            futures = {pool.submit(_one, n, s): n for n, s in tasks}
            for fut in as_completed(futures):
                name, elapsed = fut.result()
                results[name] = elapsed
    else:
        for name, sysprompt in tasks:
            n, e = _one(name, sysprompt)
            results[n] = e
    return results
