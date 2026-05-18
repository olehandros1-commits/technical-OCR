"""Pluggable LLM backends.

Why this exists:
  The extractor used to call Anthropic directly. To support local LLMs (and
  any future provider) we extracted a small interface -- LLMBackend -- that
  any provider can implement. The rest of the pipeline talks to the
  interface, never to a vendor SDK.

Public surface:
    from extractor.backends import get_backend
    backend = get_backend()             # picks from env: EXTRACTOR_BACKEND
    backend = get_backend("anthropic")
    backend = get_backend("ollama")
"""
from __future__ import annotations
import os
from .base import LLMBackend, LLMRole
from .anthropic_backend import AnthropicBackend
from .ollama_backend import OllamaBackend

__all__ = ["LLMBackend", "LLMRole", "get_backend"]


_REGISTRY = {
    "anthropic": AnthropicBackend,
    "ollama": OllamaBackend,
}


def get_backend(name: str | None = None) -> LLMBackend:
    """Return a backend instance.

    Resolution order:
      1. explicit `name` argument
      2. EXTRACTOR_BACKEND env var
      3. default: "anthropic"
    """
    chosen = (name or os.getenv("EXTRACTOR_BACKEND") or "anthropic").lower()
    if chosen not in _REGISTRY:
        raise ValueError(
            f"Unknown backend '{chosen}'. Known: {list(_REGISTRY)}"
        )
    return _REGISTRY[chosen]()
