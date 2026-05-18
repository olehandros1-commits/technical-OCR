from __future__ import annotations

import json
import os
from typing import TypeVar

from pydantic import BaseModel

from dobs.application.ports.telemetry_collector import TelemetryCollectorPort
from dobs.domain.value_objects.image_part import ImagePart
from dobs.domain.value_objects.llm_role import LLMRole
from dobs.infrastructure.adapters.llm.base import StructuredOutputCaller

T = TypeVar("T", bound=BaseModel)

_MODEL_FOR_ROLE = {
    LLMRole.CHEAP: os.getenv("OLLAMA_MODEL_CHEAP", "qwen2.5:7b"),
    LLMRole.EXTRACT: os.getenv("OLLAMA_MODEL_EXTRACT", "qwen2.5:14b"),
    LLMRole.REPAIR: os.getenv("OLLAMA_MODEL_REPAIR", "qwen2.5:14b"),
    LLMRole.VISION: os.getenv("OLLAMA_MODEL_VISION", "llama3.2-vision"),
}

_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))

_JSON_GUARD = (
    "\n\nIMPORTANT: respond with ONLY a single JSON object matching "
    "the provided schema. No prose, no markdown, no code fences."
)


class OllamaLLMBackend(StructuredOutputCaller):
    def __init__(self, /, *, telemetry: TelemetryCollectorPort) -> None:
        super().__init__(telemetry=telemetry, name="ollama")
        try:
            from ollama import AsyncClient
        except ImportError as exc:
            raise RuntimeError(
                "OllamaLLMBackend requires the `ollama` package: pip install ollama"
            ) from exc
        self._client = AsyncClient(host=_OLLAMA_HOST)

    async def _invoke(
        self, *, model: str, payload: dict[str, object]
    ) -> tuple[object, dict[str, int]]:
        resp = await self._client.chat(model=model, **payload)  # type: ignore[call-overload]  # ollama accepts kwargs as dict[str, object]
        usage: dict[str, int] = {
            "input": int(resp.get("prompt_eval_count", 0) or 0),
            "output": int(resp.get("eval_count", 0) or 0),
        }
        return resp, usage

    def _is_retryable(self, exc: Exception) -> tuple[bool, float | None]:
        if isinstance(exc, (json.JSONDecodeError, ValueError)):
            return False, None
        return True, None

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
        payload: dict[str, object] = {
            "messages": [
                {"role": "system", "content": system + _JSON_GUARD},
                {"role": "user", "content": user},
            ],
            "format": response_model.model_json_schema(),
            "options": {"num_ctx": _NUM_CTX, "temperature": 0.0},
        }

        def _parse_structured(resp: object) -> T:
            return response_model.model_validate(
                json.loads(resp["message"]["content"])  # type: ignore[index]  # ollama response
            )

        return await self._retry_loop(
            model=model,
            role=role,
            payload=payload,
            max_retries=max_retries,
            parse=_parse_structured,
        )

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
        payload: dict[str, object] = {
            "messages": [
                {"role": "system", "content": system + _JSON_GUARD},
                {
                    "role": "user",
                    "content": user,
                    "images": [img.data_b64 for img in images],
                },
            ],
            "format": response_model.model_json_schema(),
            "options": {"num_ctx": _NUM_CTX, "temperature": 0.0},
        }

        def _parse_vision(resp: object) -> T:
            return response_model.model_validate(
                json.loads(resp["message"]["content"])  # type: ignore[index]  # ollama response
            )

        return await self._retry_loop(
            model=model,
            role=LLMRole.VISION,
            payload=payload,
            max_retries=max_retries,
            parse=_parse_vision,
        )

    def supports_vision(self) -> bool:
        return True
