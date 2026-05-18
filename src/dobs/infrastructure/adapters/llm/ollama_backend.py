from __future__ import annotations

import asyncio
import json
import os
import time
from typing import TypeVar

from pydantic import BaseModel

from dobs.application.ports.telemetry_collector import CallStats, TelemetryCollectorPort
from dobs.domain.value_objects.image_part import ImagePart
from dobs.domain.value_objects.llm_role import LLMRole

T = TypeVar("T", bound=BaseModel)

_MODEL_FOR_ROLE = {
    LLMRole.CHEAP:   os.getenv("OLLAMA_MODEL_CHEAP",   "qwen2.5:7b"),
    LLMRole.EXTRACT: os.getenv("OLLAMA_MODEL_EXTRACT", "qwen2.5:14b"),
    LLMRole.REPAIR:  os.getenv("OLLAMA_MODEL_REPAIR",  "qwen2.5:14b"),
    LLMRole.VISION:  os.getenv("OLLAMA_MODEL_VISION",  "llama3.2-vision"),
}

_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))

_JSON_GUARD = (
    "\n\nIMPORTANT: respond with ONLY a single JSON object matching "
    "the provided schema. No prose, no markdown, no code fences."
)
_JSON_GUARD_SHORT = (
    "\n\nIMPORTANT: respond with ONLY a single JSON object matching "
    "the provided schema."
)


class OllamaLLMBackend:
    name = "ollama"

    def __init__(self, /, *, telemetry: TelemetryCollectorPort) -> None:
        try:
            from ollama import AsyncClient
        except ImportError as exc:
            raise RuntimeError(
                "OllamaLLMBackend requires the `ollama` package: pip install ollama"
            ) from exc
        self._client = AsyncClient(host=_OLLAMA_HOST)
        self._telemetry = telemetry

    async def call_structured(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        role: LLMRole = LLMRole.EXTRACT,
        max_retries: int = 6,
        cache_system: bool = True,
    ) -> T:
        model = _MODEL_FOR_ROLE[role]
        schema = response_model.model_json_schema()
        sys_with_guard = system + _JSON_GUARD

        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            t0 = time.monotonic()
            try:
                resp = await self._client.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": sys_with_guard},
                        {"role": "user",   "content": user},
                    ],
                    format=schema,
                    options={"num_ctx": _NUM_CTX, "temperature": 0.0},
                )
                self._telemetry.record(CallStats(
                    backend="ollama",
                    model=model,
                    role=role.value,
                    input_tokens=resp.get("prompt_eval_count", 0) or 0,
                    output_tokens=resp.get("eval_count",       0) or 0,
                    elapsed_s=round(time.monotonic() - t0, 3),
                    cost_usd=0.0,
                ))
                content = resp["message"]["content"]
                data = json.loads(content)
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                last_exc = e
                if attempt >= 2:
                    raise
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            except Exception as e:
                last_exc = e
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
        assert last_exc is not None
        raise last_exc

    async def call_vision(
        self,
        *,
        system: str,
        user: str,
        images: list[ImagePart],
        response_model: type[T],
        max_retries: int = 6,
    ) -> T:
        model = _MODEL_FOR_ROLE[LLMRole.VISION]
        schema = response_model.model_json_schema()
        sys_with_guard = system + _JSON_GUARD_SHORT

        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = await self._client.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": sys_with_guard},
                        {
                            "role": "user",
                            "content": user,
                            "images": [img.data_b64 for img in images],
                        },
                    ],
                    format=schema,
                    options={"num_ctx": _NUM_CTX, "temperature": 0.0},
                )
                content = resp["message"]["content"]
                data = json.loads(content)
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                last_exc = e
                if attempt >= 2:
                    raise
                await asyncio.sleep(backoff)
                continue
            except Exception as e:
                last_exc = e
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
        assert last_exc is not None
        raise last_exc

    def supports_vision(self) -> bool:
        return True
