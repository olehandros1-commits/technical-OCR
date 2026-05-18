from __future__ import annotations

from dobs.domain.value_objects.tier import Tier

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
        "for summary + categorisation. Tesseract for OCR."
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
        "Privacy-first: nothing leaves the box. qwen2.5:14b for extraction, qwen2.5:7b for summary."
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
    description=("Fastest cloud option for triage: Haiku for everything."),
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

_REGISTRY: dict[str, Tier] = {t.name: t for t in (PREMIUM, BALANCED, LOCAL, CHEAP)}


class TierRegistry:
    @staticmethod
    def tier_by_name(name: str) -> Tier:
        key = name.lower()
        if key not in _REGISTRY:
            raise ValueError(f"Unknown tier '{key}'. Known: {list(_REGISTRY)}")
        return _REGISTRY[key]

    @staticmethod
    def all_tiers() -> list[Tier]:
        return list(_REGISTRY.values())
