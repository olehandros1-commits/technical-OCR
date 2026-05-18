from __future__ import annotations

import asyncio
import time
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.prompts import SUMMARY_SYSTEM, TRANSACTIONS_SYSTEM, REPAIR_SYSTEM
from dobs.domain.value_objects.llm_role import LLMRole


class _Ack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


_WARM_USER = (
    'Reply with {"ok": true} only. This is a cache warm-up ping; do not '
    "extract anything from this request."
)

_DEFAULT_PROMPTS: tuple[tuple[str, str], ...] = (
    ("summary",      SUMMARY_SYSTEM),
    ("transactions", TRANSACTIONS_SYSTEM),
    ("repair",       REPAIR_SYSTEM),
)


async def warm_up_backend(
    backend: LLMBackendPort,
    *,
    prompts: Iterable[tuple[str, str]] | None = None,
) -> dict[str, float]:
    tasks = list(prompts) if prompts is not None else list(_DEFAULT_PROMPTS)

    async def _one(name: str, sysprompt: str) -> tuple[str, float]:
        t0 = time.monotonic()
        try:
            await backend.call_structured(
                system=sysprompt,
                user=_WARM_USER,
                response_model=_Ack,
                role=LLMRole.EXTRACT,
                max_retries=1,
            )
            return name, round(time.monotonic() - t0, 3)
        except Exception:
            return name, -1.0

    results_list = await asyncio.gather(*(_one(n, s) for n, s in tasks))
    return dict(results_list)
