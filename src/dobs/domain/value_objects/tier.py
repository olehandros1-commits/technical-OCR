from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True, slots=True)
class Tier:
    name: str
    display: str
    description: str
    backend: str
    model_cheap: str
    model_extract: str
    model_repair: str
    model_vision: str | None
    expected_latency_s: tuple[int, int]
    expected_cost_usd: tuple[float, float]
    enrich_default: bool
    ocr_mode: str
