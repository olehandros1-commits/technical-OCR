"""Telemetry: per-call token counts, latency, and estimated cost.

Plugged into the backends. Anthropic returns `usage` in every response;
Ollama returns `prompt_eval_count` and `eval_count`. We normalise both
into a single `CallStats` record.

Cost estimation uses public Anthropic published rates as of 2025 (USD per
million tokens). Override via env if rates change. Ollama is local =
$0.00.

Aggregation is thread-safe; the same `TelemetryCollector` instance can be
shared across parallel pipeline workers. Snapshot via `.summary()` for a
totals dict you can render in CLI or UI.
"""
from __future__ import annotations
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


# USD per MILLION tokens. Conservative defaults; override via env.
_PRICE_INPUT_PER_M = {
    "claude-sonnet-4-5":            float(os.getenv("PRICE_SONNET_INPUT",  "3.0")),
    "claude-opus-4-5":              float(os.getenv("PRICE_OPUS_INPUT",   "15.0")),
    "claude-sonnet-4-5-20250929":   float(os.getenv("PRICE_SONNET_INPUT",  "3.0")),
}
_PRICE_OUTPUT_PER_M = {
    "claude-sonnet-4-5":            float(os.getenv("PRICE_SONNET_OUTPUT", "15.0")),
    "claude-opus-4-5":              float(os.getenv("PRICE_OPUS_OUTPUT",   "75.0")),
    "claude-sonnet-4-5-20250929":   float(os.getenv("PRICE_SONNET_OUTPUT", "15.0")),
}
# Cache reads are usually 10% of normal input cost; cache writes ~125%.
_PRICE_CACHE_READ_FRAC  = 0.10
_PRICE_CACHE_WRITE_FRAC = 1.25


@dataclass
class CallStats:
    backend: str
    model: str
    role: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    elapsed_s: float = 0.0
    cost_usd: float = 0.0
    error: Optional[str] = None


def estimate_cost(model: str, in_tok: int, out_tok: int,
                  cache_read: int = 0, cache_write: int = 0) -> float:
    """USD cost from token counts using cached price table. Local = 0."""
    if "qwen" in model.lower() or "llama" in model.lower() or "mistral" in model.lower():
        return 0.0
    in_rate = _PRICE_INPUT_PER_M.get(model, 3.0) / 1_000_000.0
    out_rate = _PRICE_OUTPUT_PER_M.get(model, 15.0) / 1_000_000.0
    cost = in_tok * in_rate + out_tok * out_rate
    cost += cache_read * in_rate * _PRICE_CACHE_READ_FRAC
    cost += cache_write * in_rate * _PRICE_CACHE_WRITE_FRAC
    return cost


@dataclass
class TelemetryCollector:
    """Thread-safe aggregator. One instance per pipeline run."""
    calls: list[CallStats] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, stats: CallStats) -> None:
        with self._lock:
            self.calls.append(stats)

    def summary(self) -> dict:
        with self._lock:
            calls = list(self.calls)
        if not calls:
            return {"total_calls": 0}
        return {
            "total_calls": len(calls),
            "total_input_tokens":  sum(c.input_tokens for c in calls),
            "total_output_tokens": sum(c.output_tokens for c in calls),
            "total_cache_read":    sum(c.cache_read_tokens for c in calls),
            "total_cache_write":   sum(c.cache_write_tokens for c in calls),
            "total_elapsed_s":     round(sum(c.elapsed_s for c in calls), 2),
            "total_cost_usd":      round(sum(c.cost_usd for c in calls), 4),
            "errors":              [c.error for c in calls if c.error],
            "by_role": {
                role: sum(c.elapsed_s for c in calls if c.role == role)
                for role in {c.role for c in calls}
            },
            "by_backend": {
                b: sum(c.cost_usd for c in calls if c.backend == b)
                for b in {c.backend for c in calls}
            },
        }


# Module-level default collector. Re-bind in tests / pipeline runs as needed.
COLLECTOR = TelemetryCollector()


def get_collector() -> TelemetryCollector:
    return COLLECTOR


def set_collector(c: TelemetryCollector) -> None:
    global COLLECTOR
    COLLECTOR = c
