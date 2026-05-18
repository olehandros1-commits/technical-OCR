"""LLMBackend interface -- the contract every provider implements.

Design goals:
  * Provider-agnostic. The pipeline never sees `anthropic.Anthropic` or
    `ollama.Client` -- only `LLMBackend`.
  * Structured output is first-class. Every call returns an instance of a
    Pydantic model, not raw text. The backend handles whatever wire format
    the provider uses (tool-use, JSON-mode, function calling, schema).
  * Vision is opt-in. Backends declare whether they support image inputs;
    the OCR layer routes accordingly.
  * Roles -- EXTRACT (fast/cheap) vs REPAIR (smart/expensive) -- let the
    pipeline pick the right tier without hard-coding model names.
"""
from __future__ import annotations
import abc
from dataclasses import dataclass
from enum import Enum
from typing import Type, TypeVar
from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class LLMRole(str, Enum):
    """Logical role -- backend maps each role to a concrete model.

    CHEAP   : simple structured extraction (summary, enrich, segment-LLM
              fallback). Map to Haiku on Anthropic, qwen2.5:7b locally.
    EXTRACT : main transactions extraction (accuracy-critical). Map to
              Sonnet on Anthropic, qwen2.5:14b locally.
    REPAIR  : delta-fed correction loop. Map to Sonnet (not Opus) by
              default for cost reasons; flip to Opus via env when accuracy
              outweighs cost (e.g. EXTRACTOR_REPAIR_TIER=opus).
    VISION  : multimodal image inputs. Sonnet vision / llama3.2-vision.
    """
    CHEAP = "cheap"
    EXTRACT = "extract"
    REPAIR = "repair"
    VISION = "vision"


@dataclass
class ImagePart:
    """One image attachment for a vision call."""
    mime_type: str            # "image/png" or "image/jpeg"
    data_b64: str             # base64-encoded image bytes


class LLMBackend(abc.ABC):
    """Provider-agnostic LLM interface."""

    name: str = "base"

    @abc.abstractmethod
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
        """Call the LLM and return an instance of `response_model`."""

    def call_vision(
        self,
        system: str,
        user: str,
        images: list[ImagePart],
        response_model: Type[T],
        *,
        max_retries: int = 6,
    ) -> T:
        """Optional: vision-LLM call. Default = NotImplementedError.

        Backends that support images override this method.
        """
        raise NotImplementedError(
            f"Backend '{self.name}' does not support vision calls."
        )

    def supports_vision(self) -> bool:
        """True if `call_vision` is implemented."""
        return type(self).call_vision is not LLMBackend.call_vision
