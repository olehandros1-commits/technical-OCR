"""Anthropic Claude backend.

Wraps the Anthropic SDK behind the LLMBackend interface. All the rate-limit
handling and prompt caching that used to live in `llm.py` lives here now.
"""
from __future__ import annotations
import base64
import logging
import os
import time
from typing import Type, TypeVar

from pydantic import BaseModel

from .base import LLMBackend, LLMRole, ImagePart
from extractor.telemetry import CallStats, estimate_cost, get_collector
from extractor.spend_cap import get_cap

log = logging.getLogger(__name__)


def _coerce_to_model(raw: object, model: Type[BaseModel]) -> BaseModel:
    """Tolerant Pydantic validation.

    Anthropic tool-use occasionally emits a string-encoded JSON for a
    nested list/dict field instead of the structured value. We try the
    strict validation first, then fall back to one round of JSON-parsing
    any string values nested in the dict. This converts a 30 % chunk-loss
    failure into a clean parse without retraining.
    """
    try:
        return model.model_validate(raw)
    except Exception as strict_err:
        if not isinstance(raw, dict):
            raise strict_err
        import json as _json
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


def _usage_from_response(resp) -> dict:
    """Extract token counts from an Anthropic response. Returns empty dict if missing."""
    u = getattr(resp, "usage", None)
    if u is None:
        return {}
    return {
        "input":  getattr(u, "input_tokens", 0) or 0,
        "output": getattr(u, "output_tokens", 0) or 0,
        "cache_read":  getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }

T = TypeVar("T", bound=BaseModel)

# Role -> model mapping. Override via env.
# Cost-conscious defaults (Apr 2025 pricing per Mtok input/output):
#   Haiku 4.5: $1   / $5   (CHEAP)
#   Sonnet 4.5: $3 / $15   (EXTRACT, REPAIR by default)
#   Opus 4.5: $15  / $75   (set REPAIR_TIER=opus only when accuracy > cost)
_MODEL_FOR_ROLE = {
    LLMRole.CHEAP:   os.getenv("ANTHROPIC_MODEL_CHEAP",   "claude-haiku-4-5"),
    LLMRole.EXTRACT: os.getenv("ANTHROPIC_MODEL_EXTRACT", "claude-sonnet-4-5"),
    LLMRole.REPAIR:  os.getenv("ANTHROPIC_MODEL_REPAIR",  "claude-sonnet-4-5"),
    LLMRole.VISION:  os.getenv("ANTHROPIC_MODEL_VISION",  "claude-sonnet-4-5"),
}

MAX_TOKENS = int(os.getenv("EXTRACTOR_MAX_TOKENS", "16000"))


def _pydantic_to_tool(name: str, description: str, model: Type[BaseModel]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": model.model_json_schema(),
    }


def _retry_after_seconds(exc) -> float | None:
    """Extract Retry-After / Anthropic-specific reset header."""
    try:
        headers = exc.response.headers
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
        from datetime import datetime, timezone
        try:
            target = datetime.fromisoformat(reset.replace("Z", "+00:00"))
            delta = (target - datetime.now(timezone.utc)).total_seconds()
            if delta > 0:
                return min(delta + 1.0, 120.0)
        except ValueError:
            pass
    return None


class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(self) -> None:
        from anthropic import Anthropic
        self._client = Anthropic()

    def _tool_name_for(self, response_model: Type[BaseModel]) -> str:
        # Stable name derived from the schema title; lets the model latch.
        return "record_" + response_model.__name__.lower()

    def call_structured(
        self,
        system: str,
        user: str,
        response_model: Type[T],
        *,
        role: LLMRole = LLMRole.EXTRACT,
        max_retries: int = 6,
        cache_system: bool = True,
    ) -> T:
        from anthropic import APIStatusError, RateLimitError

        model = _MODEL_FOR_ROLE[role]
        tool = _pydantic_to_tool(
            self._tool_name_for(response_model),
            f"Return a structured {response_model.__name__} record.",
            response_model,
        )

        system_blocks: list[dict] = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        backoff = 2.0
        last_exc = None
        for attempt in range(1, max_retries + 1):
            t0 = time.time()
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=system_blocks,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    messages=[{"role": "user", "content": user}],
                )
                # Record telemetry whether or not we find a tool_use block.
                u = _usage_from_response(resp)
                call_cost = estimate_cost(model, u.get("input", 0), u.get("output", 0),
                                          u.get("cache_read", 0), u.get("cache_write", 0))
                get_collector().record(CallStats(
                    backend="anthropic",
                    model=model,
                    role=role.value,
                    input_tokens=u.get("input", 0),
                    output_tokens=u.get("output", 0),
                    cache_read_tokens=u.get("cache_read", 0),
                    cache_write_tokens=u.get("cache_write", 0),
                    elapsed_s=round(time.time() - t0, 3),
                    cost_usd=call_cost,
                ))
                # Spend cap: SpendCapExceededError raised here propagates
                # cleanly out of the pipeline (no partial results saved).
                get_cap().record(call_cost)
                for block in resp.content:
                    if block.type == "tool_use" and block.name == tool["name"]:
                        return _coerce_to_model(block.input, response_model)
                raise ValueError(
                    f"Model returned no tool_use for '{tool['name']}'. "
                    f"Stop reason: {resp.stop_reason}."
                )
            except RateLimitError as e:
                last_exc = e
                wait = _retry_after_seconds(e) or backoff
                log.warning(
                    "[anthropic] rate limit, attempt %d/%d, sleeping %.1fs",
                    attempt, max_retries, wait,
                )
                time.sleep(wait)
                backoff = min(backoff * 2, 60.0)
                continue
            except APIStatusError as e:
                last_exc = e
                if 500 <= e.status_code < 600:
                    log.warning(
                        "[anthropic] %s on attempt %d/%d, retry in %.1fs",
                        e.status_code, attempt, max_retries, backoff,
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def call_vision(
        self,
        system: str,
        user: str,
        images: list[ImagePart],
        response_model: Type[T],
        *,
        max_retries: int = 6,
    ) -> T:
        """Multimodal call: send images + text, parse structured response."""
        from anthropic import APIStatusError, RateLimitError

        model = _MODEL_FOR_ROLE[LLMRole.VISION]
        tool = _pydantic_to_tool(
            self._tool_name_for(response_model),
            f"Return a structured {response_model.__name__} record.",
            response_model,
        )

        # Anthropic image content blocks.
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
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=system_blocks,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    messages=[{"role": "user", "content": content}],
                )
                for block in resp.content:
                    if block.type == "tool_use" and block.name == tool["name"]:
                        return response_model.model_validate(block.input)
                raise ValueError(
                    f"Vision model returned no tool_use. "
                    f"Stop reason: {resp.stop_reason}."
                )
            except RateLimitError as e:
                last_exc = e
                wait = _retry_after_seconds(e) or backoff
                log.warning(
                    "[anthropic-vision] rate limit, attempt %d/%d, sleeping %.1fs",
                    attempt, max_retries, wait,
                )
                time.sleep(wait)
                backoff = min(backoff * 2, 60.0)
                continue
            except APIStatusError as e:
                last_exc = e
                if 500 <= e.status_code < 600:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
                raise
        assert last_exc is not None
        raise last_exc
