"""Ollama backend (local LLM).

Strategy:
  Ollama's chat endpoint supports a `format` parameter that accepts a JSON
  schema. The server constrains decoding so the response is a valid JSON
  matching the schema. We feed Pydantic's `model_json_schema()` straight in
  and validate the response with the same Pydantic model -- exactly the
  same contract as the Anthropic tool-use path.

Vision:
  llama3.2-vision supports an `images` field in the message. We use it
  the same way as the cloud vision path.

Configuration:
  OLLAMA_HOST                 default http://localhost:11434
  OLLAMA_MODEL_EXTRACT        default qwen2.5:14b
  OLLAMA_MODEL_REPAIR         default qwen2.5:14b   (or 32b if available)
  OLLAMA_MODEL_VISION         default llama3.2-vision
  OLLAMA_NUM_CTX              default 32768 (large -- statements are long)
"""
from __future__ import annotations
import json
import logging
import os
import time
from typing import Type, TypeVar

from pydantic import BaseModel

from .base import LLMBackend, LLMRole, ImagePart
from extractor.telemetry import CallStats, get_collector

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


_MODEL_FOR_ROLE = {
    LLMRole.CHEAP:   os.getenv("OLLAMA_MODEL_CHEAP",   "qwen2.5:7b"),
    LLMRole.EXTRACT: os.getenv("OLLAMA_MODEL_EXTRACT", "qwen2.5:14b"),
    LLMRole.REPAIR:  os.getenv("OLLAMA_MODEL_REPAIR",  "qwen2.5:14b"),
    LLMRole.VISION:  os.getenv("OLLAMA_MODEL_VISION",  "llama3.2-vision"),
}

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(self) -> None:
        try:
            from ollama import Client
        except ImportError as exc:
            raise RuntimeError(
                "OllamaBackend needs the `ollama` Python package: "
                "pip install ollama"
            ) from exc
        self._client = Client(host=OLLAMA_HOST)

    def call_structured(
        self,
        system: str,
        user: str,
        response_model: Type[T],
        *,
        role: LLMRole = LLMRole.EXTRACT,
        max_retries: int = 6,
        cache_system: bool = True,  # ignored -- Ollama caches automatically
    ) -> T:
        model = _MODEL_FOR_ROLE[role]
        schema = response_model.model_json_schema()

        # Add a short JSON-only directive -- some 7B models drift without it.
        sys_with_guard = (
            system
            + "\n\nIMPORTANT: respond with ONLY a single JSON object matching "
              "the provided schema. No prose, no markdown, no code fences."
        )

        backoff = 2.0
        last_exc = None
        for attempt in range(1, max_retries + 1):
            t0 = time.time()
            try:
                resp = self._client.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": sys_with_guard},
                        {"role": "user", "content": user},
                    ],
                    format=schema,   # constrained decoding
                    options={
                        "num_ctx": NUM_CTX,
                        "temperature": 0.0,
                    },
                )
                # Record telemetry (Ollama is local => cost=0).
                get_collector().record(CallStats(
                    backend="ollama",
                    model=model,
                    role=role.value,
                    input_tokens=resp.get("prompt_eval_count", 0) or 0,
                    output_tokens=resp.get("eval_count", 0) or 0,
                    elapsed_s=round(time.time() - t0, 3),
                    cost_usd=0.0,
                ))
                content = resp["message"]["content"]
                data = json.loads(content)
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                # Validation / schema failures -- retry once, then bubble.
                last_exc = e
                log.warning(
                    "[ollama] structured-output validation failed (%s), "
                    "attempt %d/%d", e, attempt, max_retries,
                )
                if attempt >= 2:
                    raise
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            except Exception as e:
                last_exc = e
                log.warning(
                    "[ollama] transport error (%s), attempt %d/%d, sleep %.1f",
                    e, attempt, max_retries, backoff,
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
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
        model = _MODEL_FOR_ROLE[LLMRole.VISION]
        schema = response_model.model_json_schema()

        sys_with_guard = (
            system
            + "\n\nIMPORTANT: respond with ONLY a single JSON object matching "
              "the provided schema."
        )

        backoff = 2.0
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = self._client.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": sys_with_guard},
                        {
                            "role": "user",
                            "content": user,
                            # Ollama expects raw base64 strings here.
                            "images": [img.data_b64 for img in images],
                        },
                    ],
                    format=schema,
                    options={"num_ctx": NUM_CTX, "temperature": 0.0},
                )
                content = resp["message"]["content"]
                data = json.loads(content)
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                last_exc = e
                if attempt >= 2:
                    raise
                time.sleep(backoff)
                continue
            except Exception as e:
                last_exc = e
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
        assert last_exc is not None
        raise last_exc
