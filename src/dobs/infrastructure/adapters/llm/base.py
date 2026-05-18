from __future__ import annotations

import asyncio
import json as _json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from dobs.application.ports.telemetry_collector import CallStats, TelemetryCollectorPort
from dobs.domain.value_objects.llm_role import LLMRole

T = TypeVar("T", bound=BaseModel)


def coerce_to_model(raw: object, model: type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate(raw)
    except Exception as strict_err:
        if not isinstance(raw, dict):
            raise strict_err
        coerced: dict[str, object] = {}
        for k, v in raw.items():
            if isinstance(v, str) and v.lstrip().startswith(("[", "{")):
                try:
                    coerced[k] = _json.loads(v)
                    continue
                except Exception:
                    pass
            coerced[k] = v
        return model.model_validate(coerced)


class StructuredOutputCaller(ABC):
    name: str

    def __init__(self, /, *, telemetry: TelemetryCollectorPort, name: str) -> None:
        self._telemetry = telemetry
        self.name = name

    @abstractmethod
    async def _invoke(
        self, *, model: str, payload: dict[str, object]
    ) -> tuple[object, dict[str, int]]:
        """Provider-specific call. Returns (raw_response_for_parsing, token_usage)."""
        raise NotImplementedError

    @abstractmethod
    def _is_retryable(self, exc: Exception) -> tuple[bool, float | None]:
        """Returns (retry?, explicit_wait_seconds_or_None_for_default_backoff)."""
        raise NotImplementedError

    async def _retry_loop(
        self,
        *,
        model: str,
        role: LLMRole,
        payload: dict[str, object],
        parse: Callable[[object], T],
        max_retries: int,
        cost_fn: Callable[[str, dict[str, int]], float] | None = None,
    ) -> T:
        backoff = 2.0
        last_exc: Exception | None = None
        for _ in range(1, max_retries + 1):
            t0 = time.monotonic()
            try:
                raw_resp, usage = await self._invoke(model=model, payload=payload)
                cost = cost_fn(model, usage) if cost_fn else 0.0
                self._telemetry.record(
                    CallStats(
                        backend=self.name,
                        model=model,
                        role=role.value,
                        input_tokens=usage.get("input", 0),
                        output_tokens=usage.get("output", 0),
                        cache_read_tokens=usage.get("cache_read", 0),
                        cache_write_tokens=usage.get("cache_write", 0),
                        elapsed_s=round(time.monotonic() - t0, 3),
                        cost_usd=cost,
                    )
                )
                return parse(raw_resp)
            except Exception as e:
                last_exc = e
                retryable, wait = self._is_retryable(e)
                if not retryable:
                    raise
                await asyncio.sleep(wait if wait is not None else backoff)
                backoff = min(backoff * 2, 60.0)
        assert last_exc is not None
        raise last_exc
