"""Named tier profiles.

A tier is a deliberate trade-off between quality, latency, and cost.
Each profile maps the four LLM roles (CHEAP / EXTRACT / REPAIR / VISION)
to concrete models on both backends, and carries the metadata the UI
shows in the tier-selector chip and the cost banner.

Why this exists as data, not a flag soup:
  * Business users need named tradeoffs ("our Premium tier"), not
    `--model A --repair-model B --enrich-model C`.
  * A single tier knob is what gets recorded in the audit log so we can
    answer "which tier produced this extraction" months later.
  * Replay snapshots are keyed on tier so the demo can switch tiers
    instantly with zero API spend.

Pick a tier:
  CLI:    extract-statement ... --tier balanced
  Env:    EXTRACTOR_TIER=premium
  API:    POST /jobs ?tier=local  (multipart form field)
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Tier:
    name: str                       # "premium" | "balanced" | "local" | ...
    display: str                    # short label for UI dropdowns
    description: str                # one-line value prop
    backend: str                    # "anthropic" | "ollama"
    model_cheap: str
    model_extract: str
    model_repair: str
    model_vision: Optional[str]
    expected_latency_s: tuple[int, int]   # (low, high) for 10 statements
    expected_cost_usd: tuple[float, float]  # (low, high) for 10 statements
    enrich_default: bool            # auto-enable enrichment for this tier?
    ocr_mode: str                   # "auto" | "vision" | "tesseract"


PREMIUM = Tier(
    name="premium",
    display="Premium (Opus)",
    description=(
        "Highest accuracy: Opus 4.5 for the repair loop, Sonnet for "
        "extraction, vision-LLM for OCR. For audit-grade extraction "
        "where every dollar matters."
    ),
    backend="anthropic",
    model_cheap="claude-haiku-4-5",
    model_extract="claude-sonnet-4-5",
    model_repair="claude-opus-4-5",
    model_vision="claude-sonnet-4-5",
    expected_latency_s=(120, 240),
    expected_cost_usd=(6.0, 12.0),
    enrich_default=True,
    ocr_mode="vision",
)

BALANCED = Tier(
    name="balanced",
    display="Balanced (Sonnet)",
    description=(
        "Production sweet spot: Sonnet for extraction and repair, Haiku "
        "for summary + categorisation. Tesseract for OCR. 10/10 "
        "reconciled on the bundled Ixonia etalon."
    ),
    backend="anthropic",
    model_cheap="claude-haiku-4-5",
    model_extract="claude-sonnet-4-5",
    model_repair="claude-sonnet-4-5",
    model_vision="claude-sonnet-4-5",
    expected_latency_s=(60, 180),
    expected_cost_usd=(1.7, 3.2),
    enrich_default=False,
    ocr_mode="auto",
)

LOCAL = Tier(
    name="local",
    display="Local (Ollama qwen2.5)",
    description=(
        "Privacy-first: nothing leaves the box. qwen2.5:14b for "
        "extraction, qwen2.5:7b for summary. Slower; accuracy bounded "
        "by quantisation. Recommended for regulated workloads."
    ),
    backend="ollama",
    model_cheap="qwen2.5:7b",
    model_extract="qwen2.5:14b",
    model_repair="qwen2.5:14b",
    model_vision="llama3.2-vision",
    expected_latency_s=(300, 900),
    expected_cost_usd=(0.0, 0.0),
    enrich_default=False,
    ocr_mode="tesseract",
)

CHEAP = Tier(
    name="cheap",
    display="Cheap (Haiku only)",
    description=(
        "Fastest cloud option for triage: Haiku for everything. Lower "
        "accuracy on dense tables; good for first-pass inbox triage."
    ),
    backend="anthropic",
    model_cheap="claude-haiku-4-5",
    model_extract="claude-haiku-4-5",
    model_repair="claude-haiku-4-5",
    model_vision="claude-haiku-4-5",
    expected_latency_s=(30, 90),
    expected_cost_usd=(0.3, 0.8),
    enrich_default=False,
    ocr_mode="auto",
)


_REGISTRY: dict[str, Tier] = {
    t.name: t for t in (PREMIUM, BALANCED, LOCAL, CHEAP)
}


def all_tiers() -> list[Tier]:
    return list(_REGISTRY.values())


def get_tier(name: str | None = None) -> Tier:
    """Resolve a tier from the explicit name, env, or default to balanced."""
    chosen = (name or os.getenv("EXTRACTOR_TIER") or "balanced").lower()
    if chosen not in _REGISTRY:
        raise ValueError(
            f"Unknown tier '{chosen}'. Known: {list(_REGISTRY)}"
        )
    return _REGISTRY[chosen]


def apply_tier_env(tier: Tier) -> None:
    """Set process-wide env vars so backends pick the tier's models.

    This is the bridge between the named-tier abstraction and the
    backends, which already read the model names from env. No backend
    code changes needed when a new tier is added.
    """
    os.environ["EXTRACTOR_BACKEND"] = tier.backend
    if tier.backend == "anthropic":
        os.environ["ANTHROPIC_MODEL_CHEAP"]   = tier.model_cheap
        os.environ["ANTHROPIC_MODEL_EXTRACT"] = tier.model_extract
        os.environ["ANTHROPIC_MODEL_REPAIR"]  = tier.model_repair
        if tier.model_vision:
            os.environ["ANTHROPIC_MODEL_VISION"] = tier.model_vision
    elif tier.backend == "ollama":
        os.environ["OLLAMA_MODEL_CHEAP"]   = tier.model_cheap
        os.environ["OLLAMA_MODEL_EXTRACT"] = tier.model_extract
        os.environ["OLLAMA_MODEL_REPAIR"]  = tier.model_repair
        if tier.model_vision:
            os.environ["OLLAMA_MODEL_VISION"] = tier.model_vision
