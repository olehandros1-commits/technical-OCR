"""Spend cap: hard ceiling that halts the pipeline before going over.

Configured via env: EXTRACTOR_SPEND_CAP_USD (defaults to unlimited).
The cap is checked inside the LLM backend wrappers so that even a
runaway repair loop or a bug that fires too many calls gets stopped.

Two thresholds:
  * warn_at_ratio (default 0.8): emit a warning event and keep going
  * fail_at_ratio (default 1.0): raise SpendCapExceededError

Why per-session not per-tenant for now: a multi-tenant cap would need
the request-tracing infrastructure (per-tenant collector). The single
session cap protects against the failure mode that actually happens to
users today: a debug session that accidentally re-runs cold extracts.
"""
from __future__ import annotations
import os
import threading


class SpendCapExceededError(RuntimeError):
    pass


class SpendCap:
    def __init__(self, cap_usd: float | None = None) -> None:
        env_cap = os.getenv("EXTRACTOR_SPEND_CAP_USD")
        self.cap_usd = cap_usd if cap_usd is not None else (
            float(env_cap) if env_cap else float("inf")
        )
        self.warn_at_ratio = float(os.getenv("EXTRACTOR_SPEND_WARN_RATIO", "0.8"))
        self._spent = 0.0
        self._warned = False
        self._lock = threading.Lock()

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self.cap_usd - self._spent)

    def record(self, delta_usd: float) -> tuple[bool, bool]:
        """Add `delta_usd` to the running total.

        Returns (warn_this_call, breached_this_call).
        Raises SpendCapExceededError when the cap is breached so the
        backend wrapper can convert this into a clean job-level error.
        """
        warn = False
        breached = False
        with self._lock:
            self._spent += delta_usd
            ratio = self._spent / self.cap_usd if self.cap_usd > 0 else 0
            if not self._warned and ratio >= self.warn_at_ratio and self.cap_usd != float("inf"):
                warn = True
                self._warned = True
            if self.cap_usd != float("inf") and self._spent > self.cap_usd:
                breached = True
        if breached:
            raise SpendCapExceededError(
                f"Spend cap exceeded: spent ${self._spent:.4f} of "
                f"${self.cap_usd:.2f} cap. Aborting."
            )
        return warn, breached


# Process-wide default. Re-bind per session if you need finer isolation.
CAP = SpendCap()


def get_cap() -> SpendCap:
    return CAP


def set_cap(c: SpendCap) -> None:
    global CAP
    CAP = c
