from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
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
    error: str | None = None


class TelemetryCollectorPort(Protocol):
    def record(self, stats: CallStats) -> None: ...
    def summary(self) -> dict[str, object]: ...
