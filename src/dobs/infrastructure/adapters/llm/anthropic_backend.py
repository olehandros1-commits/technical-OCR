from __future__ import annotations

import asyncio
import json as _json
import os
import time
from datetime import datetime, timezone
from typing import TypeVar

from pydantic import BaseModel

from src.dobs.application.ports.telemetry_collector import CallStats, TelemetryCollectorPort
from src.dobs.domain.value_objects.image_part import ImagePart
from src.dobs.domain.value_objects.llm_role import LLMRole

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
_CACHE_READ_FRAC  = 0.10
_CACHE_WRITE_FRAC = 1.25


def _estimate_cost(
    model: str,
    in_tok: int,
    out_tok: int,
    cache_read: int = 0,
    cache_write: int = 0,
) -> float:
    in_rate  = _PRICE_INPUT_PER_M.get(model, 3.0)  / 1_000_000.0
    out_rate = _PRICE_OUTPUT_PER_M.get(model, 15.0) / 1_000_000.0
    cost = in_tok * in_rate + out_tok * out_rate
    cost += cache_read  * in_rate * _CACHE_READ_FRAC
    cost += cache_write * in_rate * _CACHE_WRITE_FRAC
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


def _coerce_to_model(raw: object, model: type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate(raw)
    except Exception as strict_err:
        if not isinstance(raw, dict):
            raise strict_err
        coerced: dict = {}
        for k, v in raw.items():
            if isinstance(v, str) and v.lstrip().startswith(("[", "{")):
                try:
                    coerced[k] = _json.loads(v)
                    continue
                except Exception:
                    pass
            coerced[k] = v
        return model.model_validate(coerced)


def _pydantic_to_tool(name: str, model: type[BaseModel]) -> dict:
    return {
        "name": name,
        "description": f"Return a structured {model.__name__} record.",
        "input_schema": model.model_json_schema(),
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


class AnthropicLLMBackend:
    name = "anthropic"

    def __init__(self, /, *, telemetry: TelemetryCollectorPort) -> None:
        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic()
        self._telemetry = telemetry

    def _tool_name_for(self, response_model: type[BaseModel]) -> str:
        return "record_" + response_model.__name__.lower()

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
        from anthropic import APIStatusError, RateLimitError

        model = _MODEL_FOR_ROLE[role]
        tool = _pydantic_to_tool(self._tool_name_for(response_model), response_model)
        system_blocks: list[dict] = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            t0 = time.monotonic()
            try:
                resp = await self._client.messages.create(
                    model=model,
                    max_tokens=_MAX_TOKENS,
                    system=system_blocks,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    messages=[{"role": "user", "content": user}],
                )
                u = _usage_from_response(resp)
                call_cost = _estimate_cost(
                    model,
                    u.get("input", 0),
                    u.get("output", 0),
                    u.get("cache_read", 0),
                    u.get("cache_write", 0),
                )
                self._telemetry.record(CallStats(
                    backend="anthropic",
                    model=model,
                    role=role.value,
                    input_tokens=u.get("input", 0),
                    output_tokens=u.get("output", 0),
                    cache_read_tokens=u.get("cache_read", 0),
                    cache_write_tokens=u.get("cache_write", 0),
                    elapsed_s=round(time.monotonic() - t0, 3),
                    cost_usd=call_cost,
                ))
                for block in resp.content:
                    if block.type == "tool_use" and block.name == tool["name"]:
                        return _coerce_to_model(block.input, response_model)  # type: ignore[return-value]
                raise ValueError(
                    f"Model returned no tool_use for '{tool['name']}'. "
                    f"Stop reason: {resp.stop_reason}."
                )
            except RateLimitError as e:
                last_exc = e
                wait = _retry_after_seconds(e) or backoff
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, 60.0)
                continue
            except APIStatusError as e:
                last_exc = e
                if 500 <= e.status_code < 600:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
                raise
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
        from anthropic import APIStatusError, RateLimitError

        model = _MODEL_FOR_ROLE[LLMRole.VISION]
        tool = _pydantic_to_tool(self._tool_name_for(response_model), response_model)
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
        content = image_blocks + [{"type": "text", "text": user}]
        system_blocks: list[dict] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]

        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            t0 = time.monotonic()
            try:
                resp = await self._client.messages.create(
                    model=model,
                    max_tokens=_MAX_TOKENS,
                    system=system_blocks,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    messages=[{"role": "user", "content": content}],
                )
                u = _usage_from_response(resp)
                call_cost = _estimate_cost(
                    model,
                    u.get("input", 0),
                    u.get("output", 0),
                    u.get("cache_read", 0),
                    u.get("cache_write", 0),
                )
                self._telemetry.record(CallStats(
                    backend="anthropic",
                    model=model,
                    role=LLMRole.VISION.value,
                    input_tokens=u.get("input", 0),
                    output_tokens=u.get("output", 0),
                    cache_read_tokens=u.get("cache_read", 0),
                    cache_write_tokens=u.get("cache_write", 0),
                    elapsed_s=round(time.monotonic() - t0, 3),
                    cost_usd=call_cost,
                ))
                for block in resp.content:
                    if block.type == "tool_use" and block.name == tool["name"]:
                        return _coerce_to_model(block.input, response_model)  # type: ignore[return-value]
                raise ValueError(
                    f"Vision model returned no tool_use for '{tool['name']}'. "
                    f"Stop reason: {resp.stop_reason}."
                )
            except RateLimitError as e:
                last_exc = e
                wait = _retry_after_seconds(e) or backoff
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, 60.0)
                continue
            except APIStatusError as e:
                last_exc = e
                if 500 <= e.status_code < 600:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def supports_vision(self) -> bool:
        return True
