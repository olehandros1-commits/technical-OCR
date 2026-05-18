from __future__ import annotations

import threading

from dobs.application.ports.telemetry_collector import CallStats, TelemetryCollectorPort


class CallStatsCollector(TelemetryCollectorPort):
    def __init__(self, /) -> None:
        self._calls: list[CallStats] = []
        self._lock = threading.Lock()

    def record(self, stats: CallStats) -> None:
        with self._lock:
            self._calls.append(stats)

    def summary(self) -> dict:
        with self._lock:
            calls = list(self._calls)
        if not calls:
            return {"total_calls": 0}
        return {
            "total_calls": len(calls),
            "total_input_tokens": sum(c.input_tokens for c in calls),
            "total_output_tokens": sum(c.output_tokens for c in calls),
            "total_cache_read": sum(c.cache_read_tokens for c in calls),
            "total_cache_write": sum(c.cache_write_tokens for c in calls),
            "total_elapsed_s": round(sum(c.elapsed_s for c in calls), 2),
            "total_cost_usd": round(sum(c.cost_usd for c in calls), 4),
            "errors": [c.error for c in calls if c.error],
            "by_role": {
                role: sum(c.elapsed_s for c in calls if c.role == role)
                for role in {c.role for c in calls}
            },
            "by_backend": {
                b: sum(c.cost_usd for c in calls if c.backend == b)
                for b in {c.backend for c in calls}
            },
        }
