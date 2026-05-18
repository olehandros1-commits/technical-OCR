from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TypeVar

from pydantic import BaseModel

from dobs.application.ports.telemetry_collector import TelemetryCollectorPort
from dobs.domain.value_objects.image_part import ImagePart
from dobs.domain.value_objects.llm_role import LLMRole
from dobs.infrastructure.adapters.llm.base import StructuredOutputCaller, coerce_to_model

T = TypeVar("T", bound=BaseModel)

_MODEL_FOR_ROLE = {
    LLMRole.CHEAP:   os.getenv("ANTHROPIC_MODEL_CHEAP",   "claude-haiku-4-5"),
    LLMRole.EXTRACT: os.getenv("ANTHROPIC_MODEL_EXTRACT", "claude-sonnet-4-5"),
    LLMRole.REPAIR:  os.getenv("ANTHROPIC_MODEL_REPAIR",  "claude-sonnet-4-5"),
    LLMRole.VISION:  os.getenv("ANTHROPIC_MODEL_VISION",  "claude-sonnet-4-5"),
}

_MAX_TOKENS = int(os.getenv("EXTRACTOR_MAX_TOKENS", "16000"))

_PRICE_INPUT_PER_M: dict[str, float] = {
    "claude-haiku-4-5":  float(os.getenv("PRICE_HAIKU_INPUT",  "1.0")),
    "claude-sonnet-4-5": float(os.getenv("PRICE_SONNET_INPUT", "3.0")),
    "claude-opus-4-5":   float(os.getenv("PRICE_OPUS_INPUT",  "15.0")),
}
_PRICE_OUTPUT_PER_M: dict[str, float] = {
    "claude-haiku-4-5":  float(os.getenv("PRICE_HAIKU_OUTPUT",  "5.0")),
    "claude-sonnet-4-5": float(os.getenv("PRICE_SONNET_OUTPUT", "15.0")),
    "claude-opus-4-5":   float(os.getenv("PRICE_OPUS_OUTPUT",  "75.0")),
}
_CACHE_READ_FRAC = 0.10
_CACHE_WRITE_FRAC = 1.25


def _estimate_cost(model: str, usage: dict[str, int]) -> float:
    in_rate = _PRICE_INPUT_PER_M.get(model, 3.0) / 1_000_000.0
    out_rate = _PRICE_OUTPUT_PER_M.get(model, 15.0) / 1_000_000.0
    cost = usage.get("input", 0) * in_rate + usage.get("output", 0) * out_rate
    cost += usage.get("cache_read", 0) * in_rate * _CACHE_READ_FRAC
    cost += usage.get("cache_write", 0) * in_rate * _CACHE_WRITE_FRAC
    return cost


def _usage_from_response(resp: object) -> dict[str, int]:
    u = getattr(resp, "usage", None)
    if u is None:
        return {}
    return {
        "input":       getattr(u, "input_tokens",                0) or 0,
        "output":      getattr(u, "output_tokens",               0) or 0,
        "cache_read":  getattr(u, "cache_read_input_tokens",     0) or 0,
        "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


def _retry_after_seconds(exc: object) -> float | None:
    try:
        headers = exc.response.headers  # type: ignore[union-attr]
    except AttributeError:
        return None
    ra = headers.get("retry-after")
    if ra:
        try:
            return float(ra)
        except ValueError:
            pass
    reset = headers.get("anthropic-ratelimit-output-tokens-reset")
    if reset:
        try:
            target = datetime.fromisoformat(reset.replace("Z", "+00:00"))
            delta = (target - datetime.now(timezone.utc)).total_seconds()
            if delta > 0:
                return min(delta + 1.0, 120.0)
        except ValueError:
            pass
    return None


class AnthropicLLMBackend(StructuredOutputCaller):
    def __init__(self, /, *, telemetry: TelemetryCollectorPort) -> None:
        super().__init__(telemetry=telemetry, name="anthropic")
        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic()

    def _tool_for(self, response_model: type[BaseModel]) -> dict:
        return {
            "name": "record_" + response_model.__name__.lower(),
            "description": f"Return a structured {response_model.__name__} record.",
            "input_schema": response_model.model_json_schema(),
        }

    async def _invoke(self, *, model: str, payload: dict) -> tuple[object, dict[str, int]]:
        resp = await self._client.messages.create(**payload, model=model, max_tokens=_MAX_TOKENS)
        return resp, _usage_from_response(resp)

    def _is_retryable(self, exc: Exception) -> tuple[bool, float | None]:
        from anthropic import APIStatusError, RateLimitError

        if isinstance(exc, RateLimitError):
            return True, _retry_after_seconds(exc)
        if isinstance(exc, APIStatusError) and 500 <= exc.status_code < 600:
            return True, None
        return False, None

    def _extract_tool_output(self, resp: object, tool_name: str, response_model: type[T]) -> T:
        for block in resp.content:  # type: ignore[attr-defined]
            if block.type == "tool_use" and block.name == tool_name:
                return coerce_to_model(block.input, response_model)  # type: ignore[return-value]
        raise ValueError(
            f"Model returned no tool_use for '{tool_name}'. "
            f"Stop reason: {getattr(resp, 'stop_reason', '?')}."
        )

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
        tool = self._tool_for(response_model)
        system_blocks: list[dict] = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        payload = {
            "system": system_blocks,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool["name"]},
            "messages": [{"role": "user", "content": user}],
        }

        return await self._retry_loop(
            model=model, role=role, payload=payload, max_retries=max_retries,
            parse=lambda resp: self._extract_tool_output(resp, tool["name"], response_model),
            cost_fn=_estimate_cost,
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
        tool = self._tool_for(response_model)
        image_blocks = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.mime_type,
                    "data": img.data_b64,
                },
            }
            for img in images
        ]
        payload = {
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool["name"]},
            "messages": [{"role": "user", "content": image_blocks + [{"type": "text", "text": user}]}],
        }
        return await self._retry_loop(
            model=model, role=LLMRole.VISION, payload=payload, max_retries=max_retries,
            parse=lambda resp: self._extract_tool_output(resp, tool["name"], response_model),
            cost_fn=_estimate_cost,
        )

    def supports_vision(self) -> bool:
        return True
